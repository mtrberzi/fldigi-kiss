#!/usr/bin/env python3

import socket
import sys
import time

import subprocess
from fcntl import fcntl, F_GETFL, F_SETFL
from os import O_NONBLOCK, read

# config

host = '127.0.0.1'
port = 7342 # FLDIGI KISS default port

FEND = 0xC0
FESC = 0xDB
TFEND = 0xDC
TFESC = 0xDD

def kiss_encode(payload):
    msg = b''
    for x in payload:
        # handle escape bytes
        if x == FEND:
            msg += bytes([FESC, TFEND])
        elif x == FESC:
            msg += bytes([FESC, TFESC])
        else:
            msg += bytes([x])
    return payload

def kiss_decode(payload):
    msg = b''
    frame_escape = False
    for x in payload:
        # handle escape bytes
        if frame_escape:
            if x == TFESC:
                msg += bytes([FESC])
            elif x == TFEND:
                msg += bytes([FEND])
            # everything else is an error
            frame_escape = False
        elif x == FESC:
            frame_escape = True
        else:
            msg += bytes([x])
    return msg

def kiss_data_frame(payload):
    msg = b''
    msg += bytes([FEND, 0x07]) # 0 = Port 0, 7 = FLDIGI RAW
    msg += payload
    msg += bytes([FEND])
    return kiss_encode(msg)

def enable_raw_mode():
    msg = b''
    msg += bytes([FEND, 0x06]) # 0 = Port 0, 6 = FLDIGI H/W
    msg += "KISSRAW:ON".encode('ascii')
    msg += bytes([FEND])
    return kiss_encode(msg)

def send_frame(socket, frame):
    totalsent = 0
    while totalsent < len(frame):
        sent = socket.send(frame[totalsent:])
        if sent == 0:
            raise RuntimeError("connection unexpectedly closed")
        totalsent += sent

# MFSK32 framing
STX = 0x02
EOT = 0x04

found_STX = False
message = b''

def handle_message(msg, sock):
    global frotz
    cmd = msg.decode('ascii').strip() + "\n"
    print(msg)
    frotz.stdin.write(cmd.encode('ascii'))
    frotz.stdin.flush()
    time.sleep(2)
    resp = get_game_response(frotz)
    print(resp)
    send_frame(sock, kiss_data_frame(resp.encode('ascii')))

# receive and process a decoded KISS frame (all framing information is removed; frame type is the first byte)
def receive_frame_handler(frame, sock):
    global found_STX
    global message
    if len(frame) == 0:
        return
    if frame[0] != 0x07:
        # not a data/raw frame
        return
    data = frame[1:]
    # TODO refactor for the extremely unlikely case that we get STX and EOT simultaneously
    if STX in data:
        if found_STX:
            print("Warning, duplicate STX without EOT, restarting frame")
        else:
            found_STX = True
        idx = list(data).index(STX)
        message = data[idx+1:]
    elif EOT in data:
        if found_STX:
            found_STX = False
        else:
            print("Warning, EOT without STX, discarding")
        idx = list(data).index(EOT)
        message += data[0:idx]
        handle_message(message, sock)
    else:
        if found_STX:
            message += data
        # ignore data that's received outside of frame
        

def get_game_response(frotz):
    msg = ""
    while True:
        data = frotz.stdout.read()
        if data is not None:
            msg += data.decode('ascii')
            if msg.endswith(">"):
                return msg

# entry point

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((host, port))
send_frame(s, enable_raw_mode())

#send_frame(s, kiss_data_frame("TESTING 1 TESTING 2 TESTING 3 de VE3TUX".encode('ascii')))

frotz = subprocess.Popen(['/home/mtrberzi/games/frotz/dfrotz', '-h', '1000', '/home/mtrberzi/games/zork1.z5'], stdout=subprocess.PIPE, stdin=subprocess.PIPE, shell=False)

flags = fcntl(frotz.stdout, F_GETFL)
fcntl(frotz.stdout, F_SETFL, flags | O_NONBLOCK)


opening = get_game_response(frotz)
print(opening, end='')
send_frame(s, kiss_data_frame(opening.encode('ascii')))

try:
    buf = b''
    while True:
        chunk = s.recv(1024)
        if chunk == b'':
            raise RuntimeError("connection unexpectedly closed")
        buf += chunk
        while FEND in buf:
            idx = list(buf).index(FEND)
            frame = buf[0:idx]
            receive_frame_handler(kiss_decode(frame), s)
            buf = buf[idx+1:]
except:
    s.close()
    frotz.kill()
    raise

s.close()
frotz.stdin.close()
frotz.stdout.close()
frotz.kill()
