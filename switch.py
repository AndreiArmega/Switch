#!/usr/bin/python3
import sys
import struct
from dataclasses import field
from typing import List, Tuple

from sympy.codegen import Print

import wrapper
import threading
import time

from wrapper import recv_from_any_link, send_to_link, get_switch_mac, get_interface_name


def parse_ethernet_header(data):
    # Unpack the header fields from the byte array
    # dest_mac, src_mac, ethertype = struct.unpack('!6s6sH', data[:14])
    dest_mac = data[0:6]
    src_mac = data[6:12]

    # Extract ethertype. Under 802.1Q, this may be the bytes from the VLAN TAG
    ether_type = (data[12] << 8) + data[13]

    vlan_id = -1
    # Check for VLAN tag (0x8100 in network byte order is b'\x81\x00')
    if ether_type == 0x8200:
        vlan_tci = int.from_bytes(data[14:16], byteorder='big')
        vlan_id = vlan_tci & 0x0FFF  # extract the 12-bit VLAN ID
        ether_type = (data[16] << 8) + data[17]

    return dest_mac, src_mac, ether_type, vlan_id


def create_vlan_tag(vlan_id):
    # 0x8100 for the Ethertype for 802.1Q
    # vlan_id & 0x0FFF ensures that only the last 12 bits are used
    return struct.pack('!H', 0x8200) + struct.pack('!H', vlan_id & 0x0FFF)
    # For a VLAN ID of 100, the function would return a byte sequence indicating it’s a VLAN tag, which is b'\x82\x00\x00\x64'


def send_bdpu_every_sec():
    while True:
        # TODO Send BDPU every second if necessary
        time.sleep(1)


class SwitchConfig:
    priority: int
    acces_ports: tuple
    trunc_ports: tuple


def read_config(config_file: str):
    # Initialize containers
    access_ports = []
    truncated_ports = []
    priority = None

    # Open the config file and parse the data
    with open(config_file, 'r') as file:
        # Read the first line to get the priority
        first_line = file.readline().strip()
        if first_line.isdigit():
            priority = int(first_line)

        # Process each line for port entries
        for line in file:
            line = line.strip()
            parts = line.split()

            if len(parts) == 2:
                name = parts[0]
                value = parts[1]

                # Check if the second part is an integer or 'T'
                if value.isdigit():
                    access_ports.append((name, int(value)))
                elif value == "T":
                    truncated_ports.append((name, value))

    # Convert lists to tuples for immutability
    access_ports = tuple(access_ports)
    truncated_ports = tuple(truncated_ports)

    # Return the priority, access ports, and truncated ports
    return priority, access_ports, truncated_ports


def load_switch_configs(num_switches: int):
    configs = {}

    for i in range(num_switches):
        config_file = f"configs/switch{i}.cfg"
        configs[i] = read_config(config_file)

    return configs


cam_table = {}


def main():
    # init returns the max interface number. Our interfaces
    # are 0, 1, 2, ..., init_ret value + 1
    switch_id = sys.argv[1]
    switch_id = int(switch_id)
    num_interfaces = wrapper.init(sys.argv[2:])
    interfaces = range(0, num_interfaces)
    configs = load_switch_configs(3)

    print(configs[int(switch_id)])

    print("# Starting switch with id {}".format(switch_id), flush=True)
    print("[INFO] Switch MAC", ':'.join(f'{b:02x}' for b in get_switch_mac()))

    # Create and start a new thread that deals with sending BDPU
    t = threading.Thread(target=send_bdpu_every_sec)
    t.start()

    # Printing interface names
    for i in interfaces:
        print(get_interface_name(i))

    while True:
        # Note that data is of type bytes([...]).
        # b1 = bytes([72, 101, 108, 108, 111])  # "Hello"
        # b2 = bytes([32, 87, 111, 114, 108, 100])  # " World"
        # b3 = b1[0:2] + b[3:4].
        interface, data, length = recv_from_any_link()

        dest_mac, src_mac, ethertype, vlan_id = parse_ethernet_header(data)

        # Print the MAC src and MAC dst in human readable format
        dest_mac = ':'.join(f'{b:02x}' for b in dest_mac)
        src_mac = ':'.join(f'{b:02x}' for b in src_mac)

        # Note. Adding a VLAN tag can be as easy as
        # tagged_frame = data[0:12] + create_vlan_tag(10) + data[12:]

        print(f'Destination MAC: {dest_mac}')
        print(f'Source MAC: {src_mac}')
        print(f'EtherType: {ethertype}')
        print("Received frame of size {} on interface {}".format(length, interface), flush=True)

        cam_table[src_mac] = interface

        acces_dict = {interface: value for interface, value in configs[switch_id][1]}
        trunc_dict = {interface: value for interface, value in configs[switch_id][2]}

        if get_interface_name(interface) in acces_dict:
            print("We have an access port")
            came_from_access_port = True
        if get_interface_name(interface) in trunc_dict:
            print("We have an trunc port")
            came_from_access_port = False

        vlan_on = True
        if (vlan_on):

            if vlan_id == -1:
                access_to_trunk = data[0:12] + create_vlan_tag(acces_dict[get_interface_name(interface)]) + data[12:]

            trunc_to_access = data[0:12] + data[16:]

            print(cam_table)
            if dest_mac != b'\xff\xff\xff\xff\xff\xff':
                if dest_mac in cam_table:
                    print("WE HAVE A CAM TABLE MATCH")
                    if came_from_access_port:
                        print("it came from access port and printed this\n")
                        if get_interface_name(cam_table[dest_mac]) in trunc_dict:
                            send_to_link(cam_table[dest_mac], length + 4, access_to_trunk)
                        else:
                            if acces_dict[str(get_interface_name(interface))] == acces_dict[str(get_interface_name(cam_table[dest_mac]))]:
                                send_to_link(cam_table[dest_mac], length, data)

                    else:
                        if vlan_id == acces_dict[str(get_interface_name(cam_table[dest_mac]))]:
                            send_to_link(cam_table[dest_mac], length - 4, trunc_to_access)

                else:
                    for i in interfaces:
                        if i != interface:
                            if came_from_access_port:  # if iinterface is in access ports

                                print("packet  came from access port", interface)
                                if not get_interface_name(i) in acces_dict:
                                    print("mi l-a data la trunk")
                                    send_to_link(i, length + 4, access_to_trunk)
                                else:
                                    print("nu mi l-a dat la trunk")
                                    print(acces_dict[str(get_interface_name(interface))],acces_dict[str(get_interface_name(i))])
                                    if acces_dict[str(get_interface_name(interface))] == acces_dict[str(get_interface_name(i))]:
                                        print("mi la dat data cum e la ccess",get_interface_name(i))
                                        send_to_link(i, length, data)
                                # att

                            else:
                                print("came from trunc port")
                                if not get_interface_name(i) in trunc_dict:
                                    if vlan_id == acces_dict[str(get_interface_name(i))]:
                                        print("sent to", get_interface_name(i))
                                        send_to_link(i, length - 4, trunc_to_access)
                                else:
                                    send_to_link(i, length, data)

            else:
                for i in interfaces:
                    if i != interface:
                        print("WE ARE ON BROADCAST BRANCH")
                        if came_from_access_port:
                            send_to_link(i, length + 4, access_to_trunk)

                        else:
                            if vlan_id == acces_dict[str(get_interface_name(i))]:
                                send_to_link(i, length - 4, trunc_to_access)
        else:
            if dest_mac != b'\xff\xff\xff\xff\xff\xff':
                if dest_mac in cam_table:
                    send_to_link(cam_table[dest_mac], length, data)
                    print("actual data sent", data)
                else:
                    for i in interfaces:
                        if i != interface:
                            send_to_link(i, length, data)
                            print("actual data sent", data)

            else:
                for i in interfaces:
                    if i != interface:
                        send_to_link(i, length, data)
                        print("actual data sent", data)

        # TODO: Implement VLAN support
        # TODO: Implement STP support

        # data is of type bytes.
        # send_to_link(i, length, data)


if __name__ == "__main__":
    main()
