#!/usr/bin/python3
import sys
import struct
from dataclasses import field, dataclass
from enum import Enum
from token import STRING
from typing import List, Tuple

from sympy.codegen import Print
from sympy.strategies.core import switch

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


def send_bdpu_every_sec(trunc_dict,root_bridge_id,own_bridge_id):
    while True:
        # TODO Send BDPU every second if necessary
        time.sleep(1)
        if own_bridge_id == root_bridge_id:
            for ports in trunc_dict:
                for index, port in enumerate(sys.argv[2:]):
                    if port == ports:
                        ports_int = index
                root_bridge_id = own_bridge_id
                sender_bridge_ID = own_bridge_id
                sender_path_cost = 0
                bpdu = BPDUFrame(
                    src_mac=get_switch_mac(),
                    llc_length=bytes.fromhex("0026"),
                    root_bridge_id=own_bridge_id.to_bytes(8, 'big'),
                    root_path_cost=sender_path_cost,
                    bridge_id=own_bridge_id.to_bytes(8, 'big'),
                    port_id=bytes.fromhex("00FF"),


                )
                send_to_link(ports_int,48,bpdu.pack())


@dataclass
class BPDUFrame:
    dst_mac: bytes = bytes.fromhex("0180C2000000")  # 6 bytes
    src_mac: bytes = field(default_factory=lambda: bytes(6))  # 6 bytes
    llc_length: bytes = bytes.fromhex("0026")                              # 2 bytes
    dsap: int = 0x42                                 # 1 byte
    ssap: int = 0x42                                 # 1 byte
    control: int = 0x03                              # 1 byte
    flags: int = 0                                   # 1 byte
    root_bridge_id: bytes = field(default_factory=lambda: bytes(8))  # 8 bytes
    root_path_cost: int = 0                          # 4 bytes
    bridge_id: bytes = field(default_factory=lambda: bytes(8))       # 8 bytes
    port_id: bytes = field(default_factory=lambda: bytes(2))                                 # 2 bytes
    message_age: bytes = bytes.fromhex("0001")                            # 2 bytes
    max_age: bytes = bytes.fromhex("0014")                                # 2 bytes
    hello_time: bytes = bytes.fromhex("0002")                              # 2 bytes
    forward_delay: bytes = bytes.fromhex("000F")                          # 2 bytes

    def pack(self):

        return struct.pack(
            "!6s6s2sBBBB8sI8s2s2s2s2s2s",
            self.dst_mac,
            self.src_mac,
            self.llc_length,
            self.dsap,
            self.ssap,
            self.control,
            self.flags,
            self.root_bridge_id,
            self.root_path_cost,
            self.bridge_id,
            self.port_id,
            self.message_age,
            self.max_age,
            self.hello_time,
            self.forward_delay
        )

    def get_size(self):
        return len(self.pack())

    def unpack(self, data):
        fields = struct.unpack("!6s6s2sBBBB8sI8s2s2s2s2s2s", data)

        self.dst_mac = fields[0]
        self.src_mac = fields[1]
        self.llc_length = fields[2]
        self.dsap = fields[3]
        self.ssap = fields[4]
        self.control = fields[5]
        self.flags = fields[6]
        self.root_bridge_id = fields[7]
        self.root_path_cost = fields[8]
        self.bridge_id = fields[9]
        self.port_id = fields[10]
        self.message_age = fields[11]
        self.max_age = fields[12]
        self.hello_time = fields[13]
        self.forward_delay = fields[14]

        return self
#---------------------------
class SwitchConfig:
    priority: int
    acces_ports: tuple
    trunc_ports: tuple


def read_config(config_file: str):
    access_ports = []
    truncated_ports = []
    priority = None

    with open(config_file, 'r') as file:
        first_line = file.readline().strip()
        if first_line.isdigit():
            priority = int(first_line)

        for line in file:
            line = line.strip()
            parts = line.split()

            if len(parts) == 2:
                name = parts[0]
                value = parts[1]

                if value.isdigit():
                    access_ports.append((name, int(value)))
                elif value == "T":
                    truncated_ports.append((name, value))

    access_ports = tuple(access_ports)
    truncated_ports = tuple(truncated_ports)

    return priority, access_ports, truncated_ports


def load_switch_configs(num_switches: int):
    configs = {}

    for i in range(num_switches):
        config_file = f"configs/switch{i}.cfg"
        configs[i] = read_config(config_file)

    return configs

class State(Enum):
    LISTENING = "Listening"
    BLOCKED = "Blocked"
    DESIGNATED="Designated_port"

cam_table = {}


def main():
    # init returns the max interface number. Our interfaces
    # are 0, 1, 2, ..., init_ret value + 1
    switch_id = sys.argv[1]
    switch_id = int(switch_id)
    num_interfaces = wrapper.init(sys.argv[2:])
    interfaces = range(0, num_interfaces)


    configs = load_switch_configs(3)
    priority = configs[int(switch_id)][0]
    acces_dict = {interface: value for interface, value in configs[switch_id][1]}
    trunc_dict = {interface: value for interface, value in configs[switch_id][2]}

    Listening_trunc_ports = [(name, State.LISTENING) for name in trunc_dict.keys()]
    Listening_access_ports = [(name, State.LISTENING) for name in acces_dict.keys()]
    Designated_ports = [name for name in trunc_dict.keys()]

    print(Designated_ports)
    State_ports = Listening_trunc_ports + Listening_access_ports
    print(State_ports)


    own_bridge_id = priority
    root_bridge_id = own_bridge_id
    root_path_cost = 0
    root_port = -1



    print("# Starting switch with id {}".format(switch_id), flush=True)
    print("[INFO] Switch MAC", ':'.join(f'{b:02x}' for b in get_switch_mac()))

    # Create and start a new thread that deals with sending BDPU
    t = threading.Thread(target=send_bdpu_every_sec,args=(trunc_dict, root_bridge_id, own_bridge_id))
    t.start()

    # Printing interface names
    print(sys.argv[2:])
    for i in interfaces:
        print(get_interface_name(i),"with number ",i)



    while True:
        # Note that data is of type bytes([...]).
        # b1 = bytes([72, 101, 108, 108, 111])  # "Hello"
        # b2 = bytes([32, 87, 111, 114, 108, 100])  # " World"
        # b3 = b1[0:2] + b[3:4].
        interface, data, length = recv_from_any_link()


        dest_mac, src_mac, ethertype, vlan_id = parse_ethernet_header(data)

        expected_format = "!6s6s2sBBBB8sI8s2s2s2s2s2s"

        try:
            struct.unpack(expected_format, data)
            bpdu_frame=True
        except struct.error as e:
            bpdu_frame = False



        dest_mac = ':'.join(f'{b:02x}' for b in dest_mac)
        src_mac = ':'.join(f'{b:02x}' for b in src_mac)


        print(f'Destination MAC: {dest_mac}')
        print(f'Source MAC: {src_mac}')
        print(f'EtherType: {ethertype}')
        print("Received frame of size {} on interface {}".format(length, interface), flush=True)

        cam_table[src_mac] = interface

        blocked_ports = [name for name, state in State_ports if state == State.BLOCKED]
        if get_interface_name(interface) in acces_dict:
            came_from_access_port = True
        if get_interface_name(interface) in trunc_dict:
            came_from_access_port = False

        working = True
        if (working):
            print(cam_table)

            if vlan_id == -1 and not bpdu_frame:
                access_to_trunk = data[0:12] + create_vlan_tag(acces_dict[get_interface_name(interface)]) + data[12:]

            if not bpdu_frame:
                trunc_to_access = data[0:12] + data[16:]

            if not bpdu_frame or ethertype!= 38:
                if dest_mac != b'\xff\xff\xff\xff\xff\xff':
                    if dest_mac in cam_table:

                        if came_from_access_port:
                            if get_interface_name(cam_table[dest_mac]) in trunc_dict and get_interface_name(cam_table[dest_mac]) not in blocked_ports:
                                send_to_link(cam_table[dest_mac], length + 4, access_to_trunk)
                            else:
                                if get_interface_name(interface) not in trunc_dict and get_interface_name(cam_table[dest_mac]) not in trunc_dict:
                                    if acces_dict[str(get_interface_name(interface))] == acces_dict[str(get_interface_name(cam_table[dest_mac]))]:
                                        send_to_link(cam_table[dest_mac], length, data)


                        else:
                            if get_interface_name(cam_table[dest_mac]) not in trunc_dict:
                                if vlan_id == acces_dict[str(get_interface_name(cam_table[dest_mac]))]:
                                    send_to_link(cam_table[dest_mac], length - 4, trunc_to_access)
                            else:
                                if get_interface_name(cam_table[dest_mac]) in trunc_dict and get_interface_name(cam_table[dest_mac]) not in blocked_ports:
                                    send_to_link(cam_table[dest_mac], length , data)


                    else:
                        for i in interfaces:
                            if i != interface:
                                if came_from_access_port:
                                    if not get_interface_name(i) in acces_dict and  get_interface_name(i) not in blocked_ports :
                                        send_to_link(i, length + 4, access_to_trunk)

                                    else:
                                        if get_interface_name(interface) not in trunc_dict and get_interface_name(i) not in trunc_dict:
                                            if acces_dict[str(get_interface_name(interface))] == acces_dict[str(get_interface_name(i))]:
                                                send_to_link(i, length, data)


                                else:
                                    if not get_interface_name(i) in trunc_dict:
                                        if vlan_id == acces_dict[str(get_interface_name(i))]:
                                            send_to_link(i, length - 4, trunc_to_access)

                                    else:
                                        if get_interface_name(i) not in blocked_ports and get_interface_name(i)  in trunc_dict:
                                            send_to_link(i, length, data)


                else:
                    for i in interfaces:
                        if i != interface:
                            if came_from_access_port:
                                send_to_link(i, length + 4, access_to_trunk)

                            else:
                                if vlan_id == acces_dict[str(get_interface_name(i))]:
                                    send_to_link(i, length - 4, trunc_to_access)
            else:
                BPDU_sender_bridge_ID= (
                    (data[30] <<56) |
                    (data[31] <<48) |
                    (data[32] <<40) |
                    (data[33] <<32) |
                    (data[34] <<24) |
                    (data[35] <<16) |
                    (data[36] <<8) |
                     data[37]
                )
                BPDU_root_bridge_ID = (
                        (data[18] << 56) |
                        (data[19] << 48) |
                        (data[20] << 40) |
                        (data[21] << 32) |
                        (data[22] << 24) |
                        (data[23] << 16) |
                        (data[24] << 8) |
                        data[25]
                )
                BPDU_sender_path_cost = (
                        (data[26] << 24) |
                        (data[27] << 16) |
                        (data[28] << 8) |
                        data[29]
                )

                if own_bridge_id == root_bridge_id:
                    new_state_ports = []
                    for port, state in State_ports:
                        if own_bridge_id == root_bridge_id:
                            new_state_ports.append((port, State.LISTENING))
                        else:
                            new_state_ports.append((port, state))


                State_ports = new_state_ports
                if BPDU_root_bridge_ID < root_bridge_id:
                    previous_root_id = root_bridge_id
                    root_bridge_id = BPDU_root_bridge_ID
                    root_path_cost = BPDU_sender_path_cost + 10
                    root_port = get_interface_name(interface)

                    if own_bridge_id == previous_root_id:
                        State_ports = [
                            (name, State.BLOCKED)
                            if name != root_port and name not in acces_dict else (name, state)
                            for name, state in State_ports
                        ]


                    new_state_ports = []

                    for port, state in State_ports:
                        if port == root_port:
                            new_state_ports.append((port, State.LISTENING))
                        else:
                            if state == State.LISTENING and port in trunc_dict:
                                new_state_ports.append((port, State.BLOCKED))
                            else:
                                new_state_ports.append((port, state))

                    State_ports = new_state_ports

                    for ports in trunc_dict:
                        for index, port in enumerate(sys.argv[2:]):
                            if port == ports:
                                ports_int = index
                        bpdu = BPDUFrame(
                            src_mac=get_switch_mac(),
                            llc_length=bytes.fromhex("0026"),
                            root_bridge_id=own_bridge_id.to_bytes(8, 'big'),
                            root_path_cost=root_path_cost,
                            bridge_id=own_bridge_id.to_bytes(8, 'big'),
                            port_id=bytes.fromhex("00FF"),

                        )
                        for port,state in State_ports:
                            if state != State.BLOCKED and port not in acces_dict:
                                send_to_link(ports_int, 48, bpdu.pack())

                elif BPDU_root_bridge_ID == root_bridge_id:
                        if get_interface_name(interface)==root_port and BPDU_sender_path_cost+10 < root_path_cost:
                            root_path_cost = BPDU_sender_path_cost + 10
                        else:
                            if interface != root_port:
                                if BPDU_sender_path_cost > root_path_cost:
                                    if get_interface_name(interface) not in Designated_ports:
                                        Designated_ports.append(get_interface_name(interface))
                                        State_ports = [
                                            (name, State.LISTENING) if name == get_interface_name(interface) else (name, state)
                                            for name, state in State_ports
                                        ]
                elif BPDU_sender_bridge_ID == own_bridge_id:
                    State_ports = [
                        (name, State.BLOCKED) if name == get_interface_name(root_port) else (name, state)
                        for name, state in State_ports
                    ]
                else:
                    del data

if __name__ == "__main__":
    main()
