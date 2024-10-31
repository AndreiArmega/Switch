1 2 3

Toate solutiile sunt abzate pe pseudocodul de pe ocw:
### Cerinta 1: Procesul de comutare
Implementare:
```
MAC_Table[src] = P
 
if is_unicast(dst):
    if dst in MAC_Table:
        forward_frame(F, MAC_Table[dst])
    else:
        for o in Ports:
          if o != P:
               forward_frame(F, o)
else:
    # trimite cadrul pe toate celelalte porturi
    # Atentie, acest broadcast va fi diferit in cazul in
    # care avem VLAN-uri
    for o in Ports:
        if o != P:
            forward_frame(F, o)
```
-Am declarat global un dictionar cam_table care mapeaza adrese mac la porturile switcului
-Daca avem match in cam table si nu e broadcast nu trebuie sa trimitem pe toate interfetele, trimitem doar pe aceea
-Mai sunt adaugate functionalitati si chekuri pt vlan si stp ( de ex came_from_access_port sau if not bdpu_frame)
-Daca nu avem cam table match face flooding pe toate interfetele in afara de cea pe care a venit asemanator cu un hub
-Daca e broadcast face broadcast
-Pentru cerinta 1 sunt putine linii de cod asociate doar acestei functionalitati si sunt exact cele din pseudocod doar ca in loc de forward e functia din API send to link

### Cerinta 2:VLAN 
Implementare:

-Am declarat mai multe variabile noi ce ma ajuta
-Trunc dict e un dictionar cu toate porturile trunc plus litera T , e un tuplu
-Access dict asemenea , cu nr vlan (port,vlan_id)
-Acestea 2 dictionare sunt luate din config care este dictionarul unde am parsat configul
- configrile le parsez in 2 functii ajutatoare, boilerplate nimic interesant - read_config , load_switch_config
-primul pas , daca framul vine de la host , deci e packet simplu , se construieste packetul cu cei 4 bytes in plus numit acces_to_trunk - nume sugestiv de la access port pentru trunk port
- inversul cu - 4 bytes , inapoi la pachetul normal este trunc_to_access
- daca pachetul vine de la un port care e access(cam_from_access_port) sunt 2 optiuni , ori trebuie trimis la acess iar , adica la un alt port acess de la acelasi switch ori la alt switch, adica la un trunc port
- daca pacehtul vine de la trunc port sunt tot 2 optiuni , trimiti la acess , adica trunc_to_access sau trimiti la alt trunc si asta inseamna ca data ramane la fel , nu adaugi nu iei nimic
- si din aceste 4 cazuri in total avem multe ifuri care verifica fix asta in fiecare caz de comutare , in caz de cam table match , in caz de non cam table match si in caz de vraodcast simplu. Codul se repeta mult , face aceasi chestie in amre parte.
-access_to_trunk se construieste cu create_vlan_tag 
-verific cand trebuie vland_id si ce id e in pachet si daca se potrivesc trimiti pe acea interfata

### Cerinta 3:STP
Implementare:

-Am declarat o clasa ce reprezinta cadrul BPDU cu toate fieldurile:
```
dst_mac: bytes = bytes.fromhex("0180C2000000")  # 6 bytes
    src_mac: bytes =   # 6 bytes
    llc_length: bytes = bytes.fromhex("0026")                              # 2 bytes
    dsap: int = 0x42                                 # 1 byte
    ssap: int = 0x42                                 # 1 byte
    control: int = 0x03                              # 1 byte
    flags: int = 0                                   # 1 byte
    root_bridge_id: bytes   # 8 bytes
    root_path_cost:                           # 4 bytes
    bridge_id: bytes        # 8 bytes
    port_id: bytes                                 # 2 bytes
    message_age: bytes = bytes.fromhex("0001")                            # 2 bytes
    max_age: bytes = bytes.fromhex("0014")                                # 2 bytes
    hello_time: bytes = bytes.fromhex("0002")                              # 2 bytes
    forward_delay: bytes = bytes.fromhex("000F")                          # 2 bytes
```
- Multe valori sunt boilerplate , oricum nu le folosesc
- Valorile folostie sunt src mac , llc_length , root_bridge_id , root_path_cost, bridge_id
- am si metoda de pack si unpack in clasa asta
- algoritmul folosit este exact cel de pe ocw , nu am multe de adaugat aici , doar l-am tradus in variabilele mele 
```
Every 1 second:
    if switch is root:
        Send BPDU on all trunk ports with:
            root_bridge_ID = own_bridge_ID
            sender_bridge_ID = own_bridge_ID
            sender_path_cost = 0
```
- trimis BPDU fiecare secunda implementare:
	- if switch is root adica daca own_bridge_id == root_bridge_id , pe porturile trunc
		- se actualizeaza root bridge , sender bridge si sender_Patch_csot la 0 pt ca suntem root
		- creez bpdu frame si setez pe src_mac macul sursa , root_bid e own BID , BID = ow BID, root_path_cost e sender patch cost
		- trimit cadrul pe pe fiacre port trunc 

- variabile pentru stp : Listening_trunc_ports,Listening_access_ports,Designated_ports,State_ports,Blocked_ports
- cateva redundante si inutile ar trebui sterse 
- important e state ports care tine tupluri de toate porturile si in ce stare sunt si blocked ports care tehnic e inutil , dar l-am facut pt o verificare mai usoara
- not in blocked ports verifica sa nu trimita cumva cadru pe un port blocat in aprtea de forwarding
- extrag datele din BPDU in corupul principal si am urmat aproape 1:1 pseudocodul de pe ocw , toata partea asta:
```
On receiving a BPDU:
    if BPDU.root_bridge_ID < root_bridge_ID:
        root_bridge_ID = BPDU.root_bridge_ID
        # Vom adauga 10 la cost pentru ca toate link-urile sunt de 100 Mbps
        root_path_cost = BPDU.sender_path_cost + 10 
        root_port = port where BPDU was received
        if we were the Root Bridge:
            set all interfaces not to hosts to blocking except the root port  
        if root_port state is BLOCKING:
            Set root_port state to LISTENING
        Update and forward this BPDU to all other trunk ports with:
            sender_bridge_ID = own_bridge_ID
            sender_path_cost = root_path_cost
 
     Else if BPDU.root_bridge_ID == root_bridge_ID:
        If port == root_port and BPDU.sender_path_cost + 10 < root_path_cost:
            root_path_cost = BPDU.sender_path_cost + 10
 
            if BPDU.sender_path_cost > root_path_cost:
                If port is not the Designated Port for this segment:
                    Set port as the Designated Port and set state to LISTENING
    Else if BPDU.sender_bridge_ID == own_bridge_ID:
        Set port state to BLOCKING
    Else:
        Discard BPDU
```
- nu am multe de zis aici ca nu am creat eu acest algoritm , dar pasii in principiu sunt;
	-prima oara se decide cine e root bridge in o secunda doua
	- dupa care se blocheaza porturile trebuie blocate si raman de la cele 2 switchuri non root doar porturile conectate la root
	- se da constant forward la bpduuri
	- daca se gasesc cai spre root mai bune se actualizeaza
	- daca primesti pachet cu BID al tau blochezi portul
	- daca e root port blocat in deblochezi
	- daca eram root port blochezi toate truncurile in afara de root port
	- setezi designatedurile pe listening 

