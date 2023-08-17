from network import LoRa, Bluetooth, WLAN
import socket
import time
import pycom
import _thread
import json
from hashlib import sha256
from binascii import hexlify
import struct
from crypto import getrandbits
import uos
from machine import Timer
from micropython import const

from websocket_functions import ws_read_message, ws_send_message, ws_calculate_handshake
from html_page import page1, page2


mac_addr = WLAN().mac()
messages = []
message_ids = []
lock = _thread.allocate_lock()

# Packet type codings
BEACON = const(1)
NEIGHBOR_SET = const(2)
UPD_NEIGHBOR_SET = const(3)
TEXT_MESSAGE = const(4)
REQUEST_PREV_MSG = const(5)
REPLY_PREV_MSG = const(6)

# LED colors
OFF = 0x000000
RED = 0xFF0000
GREEN = 0x00FF00
BLUE = 0x0000FF
WHITE = 0xFFFAFA
YELLOW = 0xFFFF00


time.sleep(1)
wifi = WLAN()
wifi.init(mode=WLAN.AP, ssid="LoPy4_" + str(int(mac_addr[5])), auth=None, channel=1)
print("WiFi is up!")
time.sleep(1)

pycom.heartbeat(False)

lora = LoRa(mode=LoRa.LORA, frequency=868000000, region=LoRa.EU868, bandwidth=LoRa.BW_125KHZ, sf=7)
lora_sock = socket.socket(socket.AF_LORA, socket.SOCK_RAW)
lora_sock.setblocking(False)


# DOCS for CDS class
#
# Abbreviations:
#   nbr(s) - neighbor(s)
#
# Public functions:
#   send_beacon()
#   process_beacon()
#   process_neighbor_set()
#   get_is_dominant()
#
# Private functions:
#  __init__()
#  __enter_nbr_discovery_state()
#  __exit_nbr_discovery_state_alarm()
#  __send_nbr_set()
#  __check_leavers_alarm()
#  __check_dominance_alarm()
#  __check_dominance()
#
# CONST values used (simply any integer):
#  BEACON
#  NEIGHBOR_SET
#  UPD_NEIGHBOR_SET
#
# The user is expected to instantiate a single CDS object, providing as
# arguments a LoRa socket through which the object will send packets and
# a LoRa object through which the CDS object can access RSSI values.
#
# After that, the user is expected to call cds_object.send_beacon() repeatedly
# in an infinite loop at one of the threads. Take note that send_beacon()
# will put its thread to sleep for a random amount of time and only then
# the node will send out the beacon.
#
# Upon receiving any LoRa packet, the user should check the first byte for
# such flags as BEACON, NEIGHBOR_SET, and UPD_NEIGHBOR_SET; and then call
# corresponding CDS object's functions such as cds_object.process_beacon() and
# cds_object.process_neighbor_set().
#
# Structures of packets:
#  beacon_packet = [BEACON, mac address, dominance state]
#  nbr_set_packet / updated_nbr_set_packet =
#    [NEIGHBOR_SET / UPD_NEIGHBOR_SET, my_mac, nbr_mac, rssi, nbr_mac, rssi, ...]
#
# Structure of nbrs_dict:
# nbrs_dict = {
#     nbr_mac_addr_1 : [time of the last received beacon,
#                       two_hop_neighbors_info*,
#                       dominance_state,
#                       average RSS value],
#     nbr_mac_addr_2 : [...],
#     nbr_mac_addr_3 : [...],
#     ...
# }
#
# * two_hop_neighbors_info = {
#     nbr_mac_addr : 0 (RSS value),
#     2nd_hop_nbr_mac_addr_1 : RSS value,
#     2nd_hop_nbr_mac_addr_2 : RSS value,
#     ...
# }

class CDS:
    def __init__(self, lora_sock, lora):
        self.lora_sock = lora_sock
        self.lora = lora
        self.mac_addr = WLAN().mac()
        self.is_dominator = 0
        self.nbrs_dict = {}
        self.dominant_nbrs_set = set()
        self.beacon_max_delay = 5
        self.beacon_min_delay = 1
        self.nbr_discovery_state = True
        self.alarm_check_leavers = None
        self.alarm_check_dominance = None

        self.__enter_nbr_discovery_state(delay_s=60, first_time=True)


    def __enter_nbr_discovery_state(self, delay_s, first_time):
        if first_time:
            print("entering nbr discovery state for the first time")
        else:
            print("entering nbr discovery state again")

        self.nbr_discovery_state = True
        self.beacon_min_delay = 5
        self.beacon_max_delay = 15
        Timer.Alarm(lambda x: self.__exit_nbr_discovery_state_alarm(alarm=2, first_time=first_time),
                    s=delay_s, periodic=False)


    def __exit_nbr_discovery_state_alarm(self, alarm, first_time):
        if first_time:
            print("exiting nbr discovery state for the first time")
        else:
            print("exiting nbr discovery state again")
        #alarm.cancel()
        self.nbr_discovery_state = False
        if not self.alarm_check_leavers:
            self.alarm_check_leavers =  Timer.Alarm(self.__check_leavers_alarm,
                                                    s=120, periodic=True)

        self.beacon_min_delay = 40
        self.beacon_max_delay = 60

        if first_time:
            self.__send_nbr_set(NEIGHBOR_SET)
        else:
            self.__send_nbr_set(UPD_NEIGHBOR_SET)


    def __send_nbr_set(self, packet_type):
        if packet_type == NEIGHBOR_SET:
            print("ALARM: broadcasting my neighbors with type NEIGHBOR_SET")
        else:
            print("ALARM: broadcasting my neighbors with type UPD_NEIGHBOR_SET")
        packet = bytes([packet_type]) + self.mac_addr
        for nbr_mac in self.nbrs_dict.keys():
            packet += nbr_mac
            # 1 byte for rssi; from negative float to positive int
            packet += bytes([-int(self.nbrs_dict[nbr_mac][3])])
        print(packet)
        # packet = [2 or 3, my_mac, nbr_mac, rssi, nbr_mac, rssi, ... ]
        self.lora_sock.send(packet)


    def __check_leavers_alarm(self, alarm):
        if self.nbr_discovery_state:
            return

        print("ALARM: checking leavers")

        did_delete_neighbor = False

        for id in self.nbrs_dict.keys():
            # if neighbor did not send beacon for more
            # than 2 min, then consider it out of range/off
            if self.nbrs_dict[id][0] + 120 < time.time():
                print("neighbor with id:", id, "disconnected")
                del self.nbrs_dict[id]
                did_delete_neighbor = True
                # neighbor set changed, so notify neighbors about the changes
                self.__send_nbr_set(type=UPD_NEIGHBOR_SET)

        # if someone disconnected, only dominant nbrs might change their
        # dominance state, it does not affect non-dominant nbrs
        if (self.is_dominator and
                did_delete_neighbor and
                self.alarm_check_dominance == None):
            print("nbr disconnected, setting alarm to check dominance")
            self.alarm_check_dominance =  Timer.Alarm(self.__check_dominance_alarm,
                                                        s=60, periodic=False)

        if not did_delete_neighbor:
            print("no one left")


    def __check_dominance_alarm(self, alarm):
        self.alarm_check_dominance = None
        print("ALARM: delayed dominance check")
        self.__check_dominance()


    def __check_dominance(self):
        print("checking dominance")
        num_of_nbrs = len(self.nbrs_dict)
        # case if I have only 1 nbr
        if num_of_nbrs == 1:
            single_nbr_info = next(iter(self.nbrs_dict.values()))
            # if my single nbr is already dominant, then I am not dominant
            if single_nbr_info[2]:
                self.is_dominator = 0
                print("Not dominant between the two")
                packet = bytes([BEACON]) + self.mac_addr + bytes([0])
                self.lora_sock.send(packet)
                print("sent beacon")
                pycom.rgbled(OFF)
                return

            # if my single nbr is not dominant yet and it is only two of us,
            # then I proclaim myself dominant
            if len(single_nbr_info[1]) == 2:
                self.is_dominator = 1
                print("I am dominant between the two")
                packet = bytes([BEACON]) + self.mac_addr + bytes([1])
                self.lora_sock.send(packet)
                print("sent beacon")
                pycom.rgbled(BLUE)
                return
            # if my single nbr has other nbrs, then I am an edge node and
            # not dominant
            else:
                self.is_dominator = 0
                print("Not dominant between two because I am edge node")
                packet = bytes([BEACON]) + self.mac_addr + bytes([0])
                self.lora_sock.send(packet)
                print("sent beacon")
                pycom.rgbled(OFF)
                return

        # if I have 2 or more nbrs, then check their connectivity
        for id1 in self.nbrs_dict.keys():
            for id2 in self.nbrs_dict.keys():
                if id1 == id2:
                    continue

                # if two nbrs disconnected, then check whether there is
                # a third nbr that connects those two to determine who should
                # be dominant
                if id1 not in self.nbrs_dict[id2][1].keys():
                    for id3 in self.nbrs_dict.keys():
                        if id3 == id1 or id3 == id2:
                            continue
                        if id1 not in self.nbrs_dict[id3][1].keys():
                            continue
                        if id2 not in self.nbrs_dict[id3][1].keys():
                            continue
                        # if here, then there is a third nbr that connects
                        # two previous nbrs; need to check whether me or the
                        # third nbr should be dominant
                        my_nbr_set = set(self.nbrs_dict.keys())
                        my_nbr_set.add(self.mac_addr)
                        third_nbr_nbr_set = set(self.nbrs_dict[id3][1].keys())

                        # if my nbr set is a superset, then I should be dominant
                        if my_nbr_set > third_nbr_nbr_set:
                            self.is_dominator = 1
                            print("I am dominant because I connect two nbrs and am superset")
                            packet = bytes([BEACON]) + self.mac_addr + bytes([1])
                            self.lora_sock.send(packet)
                            print("sent beacon")
                            pycom.rgbled(BLUE)
                            return
                        # if my nbr set is a subset, then I shouldn't be dominant
                        elif my_nbr_set < third_nbr_nbr_set:
                            self.is_dominator = 0
                            packet = bytes([BEACON]) + self.mac_addr + bytes([0])
                            self.lora_sock.send(packet)
                            print("sent beacon")
                            print("Not dominant because I am a subset")
                            pycom.rgbled(OFF)
                            return
                        elif my_nbr_set == third_nbr_nbr_set:
                            # if me and the third have the same nbr sets, then
                            # we resolve dominance based on the sum of rssi's
                            my_rssi_sum = 0
                            for nbr_info in self.nbrs_dict.values():
                                my_rssi_sum += nbr_info[3]

                            third_nbr_rssi_sum = sum(self.nbrs_dict[id3][1].values())

                            if my_rssi_sum > third_nbr_rssi_sum:
                                self.is_dominator = 1
                                print("I am dominant because I connect 2 nbrs and have better RSSI")
                                packet = bytes([BEACON]) + self.mac_addr + bytes([1])
                                self.lora_sock.send(packet)
                                print("sent beacon")
                                pycom.rgbled(BLUE)
                                return
                            else:
                                self.is_dominator = 0
                                print("Not dominant because I have worse RSSI")
                                packet = bytes([BEACON]) + self.mac_addr + bytes([0])
                                self.lora_sock.send(packet)
                                print("sent beacon")
                                pycom.rgbled(OFF)
                                return
                        else:
                            # two sets are not equal, nor are subsets of each
                            # other; this means that each one of them has such
                            # nbrs that are not connected to another; they both
                            # need to be dominant
                            # example:
                            # 1's set is {1, 2,3,4,5} and
                            # 2's set is {2, 1,3,4,6} and
                            # 3's set is {3, 1,2} and
                            # 4's set is {4, 1,2}
                            # both, 1 and 2, connect 3 and 4; but 1 also
                            # connects 2 and 5, and 2 also connects 1 and 6;
                            # therefore, both should be dominant
                            self.is_dominator = 1
                            print("I am dominant because I connect 2 nbrs and am not super, sub, or equal")
                            packet = bytes([BEACON]) + self.mac_addr + bytes([1])
                            self.lora_sock.send(packet)
                            print("sent beacon")
                            pycom.rgbled(BLUE)
                            return

                    # if here, then there is no third nbr that connects
                    # two previous nbrs, meaning that I need to be
                    # dominant
                    self.is_dominator = 1
                    print("I am dominant because only I connect 2 nbrs")
                    packet = bytes([BEACON]) + self.mac_addr + bytes([1])
                    self.lora_sock.send(packet)
                    print("sent beacon")
                    pycom.rgbled(BLUE)
                    return

        # if here, then all nbrs are connected; need to check whether
        # there is already a dominant node or some node has other edges
        # outside our clique
        for nbr_info in self.nbrs_dict.values():
            if (len(nbr_info[1]) > num_of_nbrs + 1 or
                    nbr_info[2]):
                self.is_dominator = 0
                print('''Not dominant because it's clique and some nbr
                    is cut vertex or because its complete graph and
                    some nbr is already dominant''')
                packet = bytes([BEACON]) + self.mac_addr + bytes([0])
                self.lora_sock.send(packet)
                print("sent beacon")
                pycom.rgbled(OFF)
                return

        # if here, then we have a complete graph with no dominant
        # nodes yet; dominance is resolved based on the sum of rssi's
        my_rssi_sum = 0
        for nbr_info in self.nbrs_dict.values():
            my_rssi_sum += nbr_info[3]

        for id in self.nbrs_dict.keys():
            if my_rssi_sum < sum(self.nbrs_dict[id][1].values()):
                self.is_dominator = 0
                print("Not dominant in complete graph because of worse RSSI")
                packet = bytes([BEACON]) + self.mac_addr + bytes([0])
                self.lora_sock.send(packet)
                print("sent beacon")
                pycom.rgbled(OFF)
                return

        # if here, in the complete graph I have the best connectivity
        # to others, so I should be dominant
        self.is_dominator = 1
        print("I am dominant in complete graph because off high RSSI")
        packet = bytes([BEACON]) + self.mac_addr + bytes([1])
        self.lora_sock.send(packet)
        print("sent beacon")
        pycom.rgbled(BLUE)
        return


    # beacon interval is randomized between lower and upper boundaries
    def send_beacon(self):
        r = uos.urandom(1)
        r = int.from_bytes(r, "big") / 255
        r = (r * (self.beacon_max_delay - self.beacon_min_delay) +
            self.beacon_min_delay)
        time.sleep(r)
        packet = bytes([BEACON]) + self.mac_addr + bytes([self.is_dominator])
        self.lora_sock.send(packet)
        print("sent beacon")


    # upon receiving the beacon packet, the node pulls out nbr mac address,
    # dominance state, and rss value. If the mac address is new, then the
    # node adds the new nbr into the nbrs_dict. If not, then the node simply
    # updates the nbrs_dict. If a new mac address is received outside the
    # nbr discovery state, then the node reenters the state, which may lead
    # to CDS update.
    def process_beacon(self, recv_pkg):
        print("\nreceived beacon:", recv_pkg)
        nbr_rssi = self.lora.stats().rssi
        nbr_mac_addr = recv_pkg[1:7]
        is_nbr_dominant = recv_pkg[7]
        if is_nbr_dominant:
            self.dominant_nbrs_set.add(nbr_mac_addr)
        else:
            self.dominant_nbrs_set.discard(nbr_mac_addr)
        if nbr_mac_addr in self.nbrs_dict:
            self.nbrs_dict[nbr_mac_addr][0] = time.time()
            self.nbrs_dict[nbr_mac_addr][2] = is_nbr_dominant
            # exponential weighted moving average; alpha = 0.3
            self.nbrs_dict[nbr_mac_addr][3] = (0.7 * self.nbrs_dict[nbr_mac_addr][3] +
                                               0.3 * nbr_rssi)
        else:
            self.nbrs_dict[nbr_mac_addr] = [time.time(), None, is_nbr_dominant, nbr_rssi]
            print("got new nbr:", nbr_mac_addr)
            # if I receive a new beacon after neighbor discovery
            # state, then I need to reenter the state and broadcast
            # my updated neighborhood list
            if not self.nbr_discovery_state:
                r = uos.urandom(1)
                r = int.from_bytes(r, "big") / 255
                self.__enter_nbr_discovery_state(delay_s=30 + r * 10, first_time=False)

        print("\nneighbors:")
        for n in self.nbrs_dict.keys():
            print(n, ":", self.nbrs_dict[n])


    def process_neighbor_set(self, recv_pkg):
        print("got neighbor set:", recv_pkg)
        # structure of received packet:
        # [2, 1st_hop_nbr_mac, 2nd_hop_nbr_mac, rssi, 2nd_hop_nbr_mac, rssi, ... ]

        packet_type = recv_pkg[0]
        if packet_type == NEIGHBOR_SET:
            print("with type NEIGHBOR_SET")
        else:
            print("with type UPD_NEIGHBOR_SET")
        first_hop_neighbor_id = recv_pkg[1:7]
        two_hop_neighbors = {}
        two_hop_neighbors[first_hop_neighbor_id] = 0
        for i in range(7, len(recv_pkg), 7):
            two_hop_neighbors[recv_pkg[i:i+6]] = -recv_pkg[i+6]

        #two_hop_neighbors = [ recv_pkg[i:i+6] for i in range(1, len(recv_pkg), 6)]
        print("two_hop_neighbors:", two_hop_neighbors, "\n")
        self.nbrs_dict[first_hop_neighbor_id][1] = two_hop_neighbors

        # the node checks dominance only when it has received all
        # two-neighbor info
        for nbr_mac in self.nbrs_dict.keys():
            if self.nbrs_dict[nbr_mac][1] is None:
                return

        if packet_type == NEIGHBOR_SET:
            print("Received the last nbr set")
            self.__check_dominance()

        # if nbr sent out an updated nbr set, then the delayed dominance check
        # happens. It is delayed because if one nbr updated its set, then it
        # is likely that my others nbrs will also update their sets.
        if (packet_type == UPD_NEIGHBOR_SET and
                self.alarm_check_dominance == None):
            print("Received updated nbr set, setting alarm to check dominance")
            self.alarm_check_dominance =  Timer.Alarm(self.__check_dominance_alarm,
                                                    s=60, periodic=False)


    def get_is_dominant(self):
        return self.is_dominant



#************************************
#                                   *
#           LoRa Functions          *
#                                   *
#************************************

# sends message by LoRa
# generates id's for messages
def send_text_lora(msg):
    # setting 1 byte for packet type
    packet_type = bytes([TEXT_MESSAGE])

    # creating 4 bytes id for message
    id = getrandbits(32)
    print("Generated id:", id)
    print("id type", type(id))
    message_ids.append(id)
    while len(message_ids) > 100:
        message_ids.pop(0)

    # setting 1 byte hop limit for packet
    hop_limit = bytes([3])

    # calculating 4 bytes header checksum for packet
    cks = sha256(id + hop_limit)
    cks = cks.digest()
    cks = hexlify(cks)
    cks = cks.decode()[:4]

    packet = packet_type + id + hop_limit + cks + msg
    lora_sock.send(packet)
    print("Sent packet of length", len(packet), "with text", packet)

def process_text_message(recv_pkg):
    id = recv_pkg[1:5]
    hop_limit = recv_pkg[5]
    checksum = recv_pkg[6:10]
    msg = recv_pkg[10:].decode("utf-8")

    # calculating header checksum for comparison
    cks = sha256(id + bytes([hop_limit]))
    cks = cks.digest()
    cks = hexlify(cks)
    cks = cks[:4]

    if cks != checksum:
        print("incorrect checksum")
        print("calculated checksum", checksum)
        print("given cks", cks)
        return
    else:
        print("correct checksum")

    if len(msg) > 0:
        if ">" not in msg:
            return

        #if id not in message_ids:
        if True:
            with lock:
                messages.append(msg)
                while len(messages) > 100:
                    messages.pop(0)
                message_ids.append(id)
                while len(message_ids) > 100:
                    message_ids.pop(0)
                # send to connected via bluetooth
                chr2.value(msg)
            # send to all connected via wifi
            for client in websocket_clients:
                ws_send_message(client, msg)

    #is_dominant = cds.get_is_dominant()
    is_dominant = 1
    if is_dominant and hop_limit > 0:
        hop_limit -= 1
        # calculating new header checksum and forwarding the packet
        new_cks = sha256(id + bytes([hop_limit]))
        new_cks = new_cks.digest()
        new_cks = hexlify(new_cks)
        new_cks = new_cks.decode()[:4]
        log = "I resent a packet of " + str(len(msg)) + " with text: " + msg + "\n"
        print(log)
        f = open("logs.txt", "a")
        f.write(log)
        f.close()
        lora_sock.send(bytes([TEXT_MESSAGE]) + id + bytes([hop_limit]) + new_cks + msg)

def process_request_prev_msg(recv_pkg):
    pass

def process_reply_prev_msg(recv_pkg):
    pass

# callback function: receives messages by LoRa
def receive_lora(x):
    global lock
    recv_pkg = lora_sock.recv(256)
    if len(recv_pkg) <= 0:
        return
    print("Received packet of length", len(recv_pkg), "with text", recv_pkg)

    packet_type = recv_pkg[0]
    # no switch case in micropython(
    if packet_type == TEXT_MESSAGE:
        process_text_message(recv_pkg)
    elif packet_type == BEACON:
        cds.process_beacon(recv_pkg)
    elif packet_type == NEIGHBOR_SET or packet_type == UPD_NEIGHBOR_SET:
        cds.process_neighbor_set(recv_pkg)
    elif packet_type == REQUEST_PREV_MSG:
        process_request_prev_msg(recv_pkg)
    elif packet_type == REPLY_PREV_MSG:
        process_reply_prev_msg(recv_pkg)
    else:
        print("wrong packet type")
        return



#****************************************
#                                       *
#           Bluetooth Functions         *
#                                       *
#****************************************

# establishing connection
def conn_cb (bt_o):
    events = bt_o.events()
    if  events & Bluetooth.CLIENT_CONNECTED:
        print("Client connected")
    elif events & Bluetooth.CLIENT_DISCONNECTED:
        print("Client disconnected")

def char1_cb_handler(chr):
    global lock
    value = chr.value()
    print("Received message in characteristic = {}".format(value))
    with lock:
        messages.append(value.decode('utf-8'))
    # send via LoRa
    send_text_lora(value)
    # send to all connected via wifi
    for client in websocket_clients:
        ws_send_message(client, data)

def char2_cb_handler(chr):
    pycom.rgbled(blue)

bluetooth = Bluetooth()
bluetooth.set_advertisement(name='LoPy4', manufacturer_data="Pycom", service_uuid=0xec00)
bluetooth.callback(trigger=Bluetooth.CLIENT_CONNECTED | Bluetooth.CLIENT_DISCONNECTED, handler=conn_cb)
bluetooth.advertise(True)

srv1 = bluetooth.service(uuid=0xec00, isprimary=True, nbr_chars=2)
chr1 = srv1.characteristic(uuid=0x1234, value="Hello")
chr2 = srv1.characteristic(uuid=0x5678, value="Hello")

char1_cb = chr1.callback(trigger=Bluetooth.CHAR_WRITE_EVENT, handler=char1_cb_handler)
char2_cb = chr2.callback(trigger=Bluetooth.CHAR_READ_EVENT, handler=char2_cb_handler)

#************************************
#                                   *
#           Wi-Fi Functions         *
#                                   *
#************************************



websocket_clients = []
http = "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection:close \r\n\r\n"



# Thread for handling a client
def client_thread(clientsocket, address):
    global lock
    req = clientsocket.recv(4096)

    #print("Received: {}".format(req.decode()))

    if "Upgrade: websocket" in str(req):
        handshake = ws_calculate_handshake(req)
        clientsocket.send(handshake)
        print("handshake done")
        websocket_clients.append(clientsocket)

        while True:
            try:
                data = ws_read_message(clientsocket)
            except ValueError:
                print(websocket_clients)
                websocket_clients.remove(clientsocket)
                print(websocket_clients)
                break

            if data:
                print(data)
                with lock:
                    messages.append(data)
                print(messages)
                for client in websocket_clients:
                    ws_send_message(client, data)

                chr2.value(data)
                send_text_lora(data)

        clientsocket.close()
        print(address, "disconnected")
        return


    if "GET / " in str(req):
        while (len(messages) > 100):
            messages.pop()

        result = http + page1
        for i in messages:
            result += "<li class=\"list-group-item\">" + i + "</li>"

        clientsocket.send((result + page2).encode())

    elif "/favicon" in str(req):
        pass

    elif "/messages.json" in str(req):
        # Send messages list as a JSON array
        jsonresponse = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection:close \r\n\r\n"
        clientsocket.send((jsonresponse + json.dumps(messages)).encode())

    # Close the socket and terminate the thread
    clientsocket.close()
    print(address, "disconnected")


#********************************
#                               *
#           Main Code           *
#                               *
#********************************

lora.callback(trigger=LoRa.RX_PACKET_EVENT, handler=receive_lora)

# Set up server socket
serversocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
serversocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
serversocket.bind(("192.168.4.1", 80))
serversocket.setblocking(False)

# Accept maximum of 5 connections at the same time
serversocket.listen(5)

cds = CDS(lora_sock, lora)

def sending_beacons():
    while True:
        cds.send_beacon()

_thread.start_new_thread(sending_beacons, ())

while True:
    time.sleep(0.1)
    try:
        (clientsocket, address) = serversocket.accept()
        print(address[0], "connected")
        _thread.start_new_thread(client_thread, (clientsocket, address[0]))
    except:
        pass






#d
