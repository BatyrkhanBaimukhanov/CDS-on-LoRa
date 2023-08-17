import struct
from hashlib import sha1
from binascii import b2a_base64 as b64encode

# websocket(ws) constants
FIN    = 0x80 #128
OPCODE = 0x0f #15
MASKED = 0x80
PAYLOAD_LEN = 0x7f #127
PAYLOAD_LEN_EXT16 = 0x7e #126
PAYLOAD_LEN_EXT64 = 0x7f #127
OPCODE_TEXT = 0x01 #1
CLOSE_CONN  = 0x8 #8
EXIT_FLAG = bytes([3, 233])
GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
template ='HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n'


def ws_read_message(client):
    b1, b2 = client.recv(2)
    fin    = b1 & FIN
    opcode = b1 & OPCODE
    masked = b2 & MASKED
    payload_length = b2 & PAYLOAD_LEN

    if payload_length == 126:
        payload_length = struct.unpack(">H", client.recv(2))[0]
    elif payload_length == 127:
        payload_length = struct.unpack(">Q", client.recv(8))[0]

    masks = client.recv(4)
    chars_ascii = ""
    decoded = []
    data = client.recv(payload_length)

    for char in data:
        char ^= masks[len(chars_ascii) % 4]
        chars_ascii += chr(char)
        decoded.append(char)

    decoded = bytes(decoded)
    if decoded == EXIT_FLAG:
        return None
    decoded = decoded.decode("utf-8")
    return decoded


def ws_send_message(client, message):
    payload = message.encode('UTF-8')
    payload_length = len(payload)

    data_to_send = bytes([ (FIN | OPCODE_TEXT) ] )  \
         + bytes([ payload_length if payload_length <= 0x7D else 0x7E ] )  \
         + (struct.pack('>H', payload_length) if payload_length >= 0x7E else b'') \
         + (bytes(payload) if payload else b'')
    client.send(data_to_send)


def ws_calculate_handshake(req):
    lines = str(req).split("\\r\\n")
    key = None
    for line in lines[1:]:
        if not line :continue
        header = line.split(": ")
        if header[0] == "Sec-WebSocket-Key":
            print(header[1])
            key = header[1]
            break

    # compute Response Key
    hash = sha1(key.encode() + GUID.encode())
    d = hash.digest()
    response_key = b64encode(d).strip().decode('ASCII')
    handshake = template%response_key
    return handshake.encode()
