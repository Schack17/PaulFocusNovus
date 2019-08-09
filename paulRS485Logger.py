#!/usr/bin/python
# -*- coding: utf-8 -*-
import os, sys, time, datetime, logging, readline
import threading, serial, requests, time
from enum import Enum
import codecs, binascii
from logging.handlers import TimedRotatingFileHandler
from openhab import openHAB

oh_host = 'localhost'
base_url = 'http://{oh_host}:8080/rest'.format(oh_host=oh_host)
logDir = '/var/log/ventilation-system'
uniqueData = {}

outsiteTemp = 0.0
lastUpdateOutsiteTemp = datetime.datetime.now()
lastOtherData = []
temp1 = 0
temp2 = 0
temp3 = 0
temp4 = 0

masterAdr = [0x01, 0x01]
myAdr = [0x01, 0x02]
class Command(Enum):
    STATUS = 0x0
    BROADCAST_REQUEST = 0x80
    BROADCAST_ANSWER = 0x81
    # = 0x82
    # = 0x83
    ALIVE = 0x84
    GET_SET = 0x85
    ASK = 0x86
    OTHER = 0x87

# logging.basicConfig(level=logging.DEBUG, 
#        format='%(asctime)s %(message)s',
#        datefmt='%Y-%m-%d %H:%M:%S.%f')
if not os.path.exists(logDir):
    os.makedirs(logDir)

port = '/dev/ttyUSB0'
# port = '/dev/serial0'
baud = 9600


def createLogger(filename, logname):
    handler = TimedRotatingFileHandler(filename, when="midnight", interval=1)
    handler.suffix = "%Y%m%d"
    logTmp = logging.getLogger(logname)
    logTmp.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    logTmp.addHandler(handler)
    return logTmp

def crc16_ccitt(crc, data):
    msb = crc >> 8
    lsb = crc & 255
    for c in data:
        # x = ord(c) ^ msb
        x = c ^ msb
        x ^= (x >> 4)
        msb = (lsb ^ (x >> 3) ^ (x << 4)) & 255
        lsb = (x ^ (x << 5)) & 255
    return (msb << 8) + lsb

def formatLeadingZero(str):
    return '0' + str if len(str) < 2 else str

def novus_crc(data):
    crc = crc16_ccitt(0, data)
    # '3254' --> '0xcb6' --> 'b6 0c'
    #crcHexStr = '{0} {1}'.format(formatLeadingZero(hex(crc)[-2:]), formatLeadingZero(hex(crc)[2:][:-2]))
    # return bytearray.fromhex(crcHexStr)
    try:
        return [int(formatLeadingZero(hex(crc)[-2:]), 16), int(formatLeadingZero(hex(crc)[2:][:-2]), 16)]
    except:
        print('Error calc crc: data={0} crc={1}'.format(data, crc))
        pass
    return []


def validate(data):
    return validateCrc(data) and expectedDataLength(data) == len(data[6:]) # or data[2] == Command.OTHER.value)

def validateCrc(data):
    refCrc = data[4:6]
    crc = novus_crc(data[0:4] + data[6:])
    return refCrc == crc

def buildCommand(cmd, data, adr=masterAdr, dataLen=None):
    if not dataLen:
        dataLen = len(data)
        if cmd == Command.OTHER.value:
            dataLen += 0x80
    payload = adr + [cmd.value, dataLen]
    crc = novus_crc(payload + data)
    return payload + crc + data

def writeAirLevel(level):
    writeSer(buildCommand(Command.GET_SET, [0x28, 0x00, level]))

    # 0x1d --> L1
    # 0x7c ?
    # 0x2d --> L2
    # 0x1f ?
    # 0x3d --> L3
    writeSer(buildCommand(Command.OTHER, [0x00, 0x7c, 0x1d], adr=[0x01, 0x01], dataLen=0x83))

    writeSer(buildCommand(Command.GET_SET, [0x27, 0x0, level, 0x29, 0x0, level]))

def writeSer(data):
    payload = bytearray(data)
    # hexstr = 'Write: L={len:02d}: {hex}'.format(time=datetime.datetime.now(), len=len(payload), hex=' '.join(binascii.hexlify(x) for x in payload))
    hexstr = 'Write: L={len:02d}: {hex}'.format(time=datetime.datetime.now(), len=len(payload), hex=' '.join('{:02x}'.format(x) for x in payload))
    print(hexstr)
    log.debug(hexstr)
    ser.writelines([payload])

def expectedDataLength(data):
    if data[3] >= 0x80:
        return int(hex(data[3] - 0x80), 16)
    return int(hex(data[3]), 16)

def getDataLength(reading):
    try:
        return ord(reading[3])

        # return int(codecs.encode(reading[3], 'hex'))
    except:
        pass
    return 0

def getCommandId(reading):
    try:
        return int(codecs.encode(reading[2], 'hex'))
    except:
        pass
    return 0

def isCommand(cmd):
    return cmd == Command.STATUS.value or (cmd >= Command.BROADCAST_REQUEST.value and cmd <= Command.OTHER.value)

def temp2Hex(temp):
    return int((temp+20)*2)

def hex2Temp(value):
    return (value / 2) - 20

def extractTemp(b):
    return (b[3] << 8 | b[2]) / 10.0

def temp2Hex2(temp):
    return int((temp+0x80)*2)

def temp2Hex3(temp):
    return int(temp*100)

def hex2Temp2(value):
    return (value / 2) - 0x80

def updateOutsideTemp():
    global outsiteTemp
    outsiteTemp = round(float(getItemValue('HeatPump_Temperature_1')) * 2) / 2
    # print(outsiteTemp)
    
def readNovus():
    global lastUpdateOutsiteTemp
    connected = False
    while not connected:
        connected = True

        time.sleep(1)

        # seq = []
        count = 0 ## row index
        lastdata = None
        while True:
            if lastUpdateOutsiteTemp < datetime.datetime.now() - datetime.timedelta(minutes=+1):
                lastUpdateOutsiteTemp = datetime.datetime.now()
                threading.Thread(target=updateOutsideTemp, args=[]).start()

            #if count == 5:
            #    writeSer(buildCommand(Command.BROADCAST_ANSWER, []))
            #elif count == 7:
            #    writeAirLevel(1)
            #elif count > 5 and int(round(time.time() * 1000)) % 100 == 0:
            #    writeSer(buildCommand(Command.ALIVE, []))

            reading = ser.readline()
            # print('{0} --> {1}'.format(type(reading), reading))
            count += 1
            if not reading or len(reading) <= 0:
                continue
            if lastdata:
                reading = lastdata + reading
                lastdata = None
            #if getCommandId(reading) > 80 and getCommandId(reading) < 90:
            #    print('{0}'.format(codecs.encode(reading[2], 'hex')))
            # hex = ' '.join(binascii.hexlify(x) for x in reading)
            if len(reading) < 6:
                lastdata = reading
                continue
            elif reading and getDataLength(reading) > len(reading)-6 and (getCommandId(reading)!=87 or len(reading)==32):
#                hexstr = 'L={len:02d}: {hex}'.format(time=datetime.datetime.now(), len=len(reading), hex=' '.join(binascii.hexlify(x) for x in reading))
#                print('{0} {1} {2}'.format(int(codecs.encode(reading[3], 'hex')), len(reading)-6, hexstr))
                lastdata = reading
                continue

#            if reading and lastdata and len(lastdata) == 32 and \
#                    (len(reading) < 3 or (codecs.encode(reading[2], 'hex') >= 80 and codecs.encode(reading[2], 'hex') < 90)):
#                reading += lastdata

#            lastdata = reading
            data = []
            if reading and len(reading) > 0:
                for x in reading:
                    data.append(int(binascii.hexlify(x), 16))
                try:
                    if not consumePackage(data):
                        lastdata = reading
                        continue
                except Exception as err:
                    print('Error consumePackage: data={0} erro={1}'.format(' '.join('{:02x}'.format(x) for x in data), err))
                    log.exception('Error consumePackage: data={0}'.format(' '.join('{:02x}'.format(x) for x in data)))
                    pass

def consumePackage(data, recursion=0):
    global lastOtherData
    global temp1
    global temp2
    global temp3
    global temp4
    # hexstr = '{time:%Y-%m-%d %H:%M:%S.%f} L={len:02d}: {hex}'.format(time=datetime.datetime.now(), len=len(reading), hex=' '.join(binascii.hexlify(x) for x in reading))
    #print(type(reading))

    if recursion > 10:
        log.debug('Cancel consume recursion Data: {0}'.format(' '.join('{:02x}'.format(x) for x in data)))
        return True

    #if len(data) > 9 and data[0] == 0x01 and data[1] == 0x01 and data[2] == Command.OTHER.value and data[3] == 0x83:
    #    consumePackage(data[0:9])
    #    data = data[9:]
    if expectedDataLength(data) + 6 > len(data):
        print('Expected Lenght: {0}, Length: {1}, Data: {2}'.format(expectedDataLength(data) + 6, len(data), ' '.join('{:02x}'.format(x) for x in data)))
        return False

    valid = False
    lastdata = []
    while not valid and len(data) >= 6 and lastdata != data:
#        hexstr = 'CRC: {crc} L={len:02d}: {hex}'.format(crc=valid, time=datetime.datetime.now(), len=len(data), hex=' '.join('{:02x}'.format(x) for x in data))
#        print(hexstr)
        lastdata = data
        valid = validate(data)
        hexstr = 'CRC: {crc} L={len:02d}: {hex}'.format(crc=valid, time=datetime.datetime.now(), len=len(data), hex=' '.join('{:02x}'.format(x) for x in data))
        if not valid and len(data) >= 6:
            if len(data) >= 20 and data[0]==0x00 and data[1]==0x00 and data[2]==0x00 and data[3]==0x03:
                consumePackage(data[0:6+14], recursion=recursion+1)
                data = data[6+14:]
            elif data[2] in [item.value for item in Command] and data[2] != Command.STATUS.value:
                consumePackage(data[0:6+expectedDataLength(data)], recursion=recursion+1)
                data = data[6+expectedDataLength(data):]
            else:
                while not isCommand(data[2]):
                    data = data[1:]
                if data[2] != Command.OTHER.value:
                    if isCommand(data[2]):
                        consumePackage(data[0:6+expectedDataLength(data)], recursion=recursion+1)
                        # consumePackage(data[0:6+int(hex(data[3]), 16)])
                    # data = data[6+int(hex(data[3]), 16):]
                    data = data[6+expectedDataLength(data):]
    #            hexstr = 'CRC: {crc} L={len:02d}: {hex}'.format(crc=valid, time=datetime.datetime.now(), len=len(data), hex=' '.join('{:02x}'.format(x) for x in data))
    hexstr = 'L={len:02d}: {hex}'.format(time=datetime.datetime.now(), len=len(data), hex=' '.join('{:02x}'.format(x) for x in data))
    # logUniqueData(data, hexstr)
    hexstr = 'CRC: {} {}'.format(valid, hexstr)
    #hexstr = 'CRC: {crc} L={len:02d}: {hex}'.format(crc=valid, time=datetime.datetime.now(), len=len(data), hex=' '.join(binascii.hexlify(x) for x in reading))
    if not valid:
        if len(data) > 0:
            print(hexstr)
    elif not isCommand(data[2]):
        hexstr = 'Found new command! ' + hexstr
        print(hexstr)
    elif not data[1] in [0x00, 0x01, 0x04, 0x05, 0x08, 0x09, 0xff]:
        hexstr = 'Found new address! ' + hexstr
        print(hexstr)
    elif data[0] == 0 and data[1] == 0 and data[2] == Command.STATUS.value:
        hexstr += ' --> ' + extractTime(data)

    if len(data) > 6 and outsiteTemp > 0.0:
        t = [temp2Hex(outsiteTemp), temp2Hex(outsiteTemp-0.5), temp2Hex(outsiteTemp-1), temp2Hex(outsiteTemp-1.5), temp2Hex(outsiteTemp-2)]
        t += [temp2Hex2(outsiteTemp), temp2Hex2(outsiteTemp-0.5), temp2Hex2(outsiteTemp-1), temp2Hex2(outsiteTemp-1.5), temp2Hex2(outsiteTemp-2)]
        for b in data[6:]:
            if b in t and not b == 85 and (len(data) != 9 or not (data[7]==0xd4 and data[8]==0x6c)):
                out = 'Found {3}Temp: ~{0} ({1}) in {2}'.format(outsiteTemp, hex(b), hexstr, 'Hot ' if data[7] in [0x05, 0x9d] else '')
                print(out)
                log.debug(out)
                break
        '''if len(data) > 7:
            t += [temp2Hex3(outsiteTemp), temp2Hex3(outsiteTemp-0.5), temp2Hex3(outsiteTemp-1), temp2Hex3(outsiteTemp-1.5), temp2Hex3(outsiteTemp-2)]
            for b in data[6:]:
                if b in t and not b == 85:
                    out = 'Found {3} Temp: ~{0} ({1}) in {2}'.format(outsiteTemp, hex(b), hexstr, 'Hot' if data[7] in [0x05, 0x9d] else '')
                    print(out)
                    log.debug(out)
                    break'''

    if len(data) >= 9 and data[2] == Command.OTHER.value:
        hexstr += ' Temp:? {0} / {1}'.format(hex2Temp(data[8]), hex2Temp2(data[8]))
    #if len(data) >= 9 and data[2] == Command.OTHER.value:
    #    hexstr += ' Temp:? {0} / {1}'.format(hex2Temp(data[8]), hex2Temp2(data[8]))

    #hexstr = 'L={len:02d}: {hex}'.format(time=datetime.datetime.now(), len=len(reading), hex=' '.join(binascii.hexlify(x) for x in reading))
    # if len(data) != 6 and len(data) != 9:
        # logExt.debug(hexstr)

    # data = (int(binascii.hexlify(x), 16) for x in reading)
    if False and len(data) >= 6 and data[0:2] == myAdr and data[2] == Command.BROADCAST_REQUEST.value:
        # TODO: vorletztes Byte - was setzen?
        # TODO: Add SN as Text                                       ___Bus Version__   16?        ___Firmware S/N_________________________________________________
        writeSer(buildCommand(Command.BROADCAST_ANSWER, [0x00, 0x00, 0x01, 0x07, 0x01, 0x90, 0x00, 0x45, 0x54, 0x41, 0x30, 0x30, 0x33, 0x36, 0x45, 0x32, 0x39, 0x41]))
    elif len(data) == 6 and data[0:2] == myAdr and data[2] == Command.BROADCAST_ANSWER.value:
        print('Login ok')
    elif len(data) == 6 and data[0:2] == myAdr and data[2] == Command.ALIVE.value:
        # TODO: Data? Hardcoded id?
        writeSer(buildCommand(Command.GET_SET, [0x41, 0x00, 0x00]))
    elif len(data) == 6 and data[0:2] == myAdr and data[2] == Command.ASK.value: # every 5 seconds
        # TODO: Calc DATA?
        writeSer(buildCommand(Command.OTHER, lastOtherData))
    #elif len(data) == 9 and data[0] == 0x01 and data[1] == 0x00 and data[2] == Command.GET_SET.value and data[3] == 0x03 and data[6] not in [0x90, 0x1a, 0x1d, 0x08]:
    #    print(str(data[0]))
    #int(binascii.hexlify(reading[0])) == 0x01 and 
    #    hexstr = 'L={len:02d}: {hex}'.format(time=datetime.datetime.now(), len=len(reading), hex=' '.join(binascii.hexlify(x) for x in reading))
    #    print(hexstr)
        # log.debug(hexstr)
    #    writeSer(buildCommand(Command.ALIVE, []))

    if len(data) == 9 and data[2] == Command.OTHER.value:
        lastOtherData = data[6:]

    if len(data) == 25 and data[2] == Command.GET_SET.value:
        temp = extractTemp(data[9:13])
        if temp > 0 and temp != temp1:
            temp1 = setTemp('novus300_TempIndoorIn', temp)
        temp = extractTemp(data[13:17])
        if temp > 0 and temp != temp2:
            temp2 = setTemp('novus300_TempOutdoor', temp)
        temp = extractTemp(data[17:21])
        if temp > 0 and temp != temp3:
            temp3 = setTemp('novus300_TempHouseAirOut', temp)
        temp = extractTemp(data[21:25])
        if temp > 0 and temp != temp4:
            temp4 = setTemp('novus300_TempIndoor', temp)
        # fan = extractFanLevel(data, 0x81, 9)
        # if fan > 0 and fan != fan1:
        #     hexstr += ' Temp Out: {0} -- {1}'.format(fan, outsiteTemp)
        #     fan1 = setFanLevel(2, fan)
        # fan = extractFanLevel(data, 0x82, 13)
        # if fan > 0 and fan != fan2:
        #     hexstr += ' Temp Out: {0} -- {1}'.format(fan, outsiteTemp)
        #     fan2 = setFanLevel(2, fan)
        # fan = extractFanLevel(data, 0x83, 17)
        # if fan > 0 and fan != fan3:
        #     fan3 = setFanLevel(3, fan)
        # fan = extractFanLevel(data, 0x84, 21)
        # if fan > 0 and fan != fan4:
        #     fan4 = setFanLevel(4, fan)
    elif len(data) == 12 and (' '.join('{:02x}'.format(x) for x in data)).startswith('01 00 85 06'):
    #if len(data) == 12 and (' '.join(binascii.hexlify(x) for x in reading)).startswith('01 00 85 06'):
        # value = str(int(codecs.encode(reading[-1], 'hex'), 16))
        value = str(data[-1])
        print(value)
        setAirLevel(value)
        #setAirLevel(str(int.from_bytes(reading[-1])))

    logUniqueData(data, hexstr)
    log.debug(hexstr)

    return True

def logUniqueData(data, hexstr):
    dataStart = 6
    # if data[2] != Command.OTHER.value or data[3] != 0x83:
    #     return
    if len(data) <= 6 or data[2] == Command.STATUS.value:
        return
    if data[2] == Command.GET_SET.value:
        if data[dataStart] == 0x55:
            return
        # if data[dataStart] in [0x08, 0x1a, 0x90, 0x1d, 0x55]:
        dataStart = 7
        if len(data) == 25: # and data[9] == 0x81 and data[13] == 0x82 and data[17] == 0x83 and data[21] == 0x84:
            # print(data[9:13])
            # hexstr += '81: {0}; 82: {1}; 83: {2}; 84: {3}'.format(data[9:12]) #, hex2Temp3(data[13:16]), hex2Temp3(data[17:20]), 0) #, hex2Temp3(data[21:24]))
           hexstr += ' Temp: 81: {0}; 82: {1}; 83: {2}; 84: {3}'.format(extractTemp(data[9:13]), extractTemp(data[13:17]), extractTemp(data[17:21]), extractTemp(data[21:25]))

    
    key = keyStart = 'L={:02d}: '.format(len(data))
    dataStr = ''
    for i, byte in enumerate(data):
        if i < 6:
            keyStart += '{:02x} '.format(byte)
        if i in [4, 5]:
            continue
        if i < dataStart:
            key += '{:02x} '.format(byte)
        else:
            dataStr += '{:02x} '.format(byte)
    if key in uniqueData:
        if uniqueData[key] == dataStr:
            return
    logExt.debug(hexstr)
    if key in uniqueData and data[2] != Command.STATUS.value:
        hexstr2 = ' ' * (hexstr.find(keyStart) + len('L={:02d}: '.format(len(data))) + (len(data) * 3) - len(dataStr))
        # hexstr2 = ' ' * (len(hexstr) - len(dataStr) + 1)
        dataBytesPrev = uniqueData[key].rstrip(' ').split(' ')
        dataBytes = dataStr.rstrip(' ').split(' ')
        for i in range(0, max(len(dataBytesPrev), len(dataBytes))):
            if i >= len(dataBytesPrev):
                break
            byte = dataBytesPrev[i]
            if i < len(dataBytes) and dataBytes[i] == byte:
                byte = '  ' # '__'
            hexstr2 += '{} '.format(byte)    
        logExt.debug(hexstr2) # + ' --> ' + keyStart + ' Len: ' + str(len(data) * 3) + ' Len(dataStr): ' + str(len(dataStr)))
    uniqueData[key] = dataStr

def extractTime(data):
    weekDays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    return '{0} {1}.{2}.{3} {4}:{5}:{6}'.format(weekDays[data[8]], data[9], data[10], data[11], data[16], data[15], data[14])

def extractFanLevel(data, fanId, dataPos):
    if data[dataPos] != fanId:
        return -1
    elif data[dataPos+3] <= 0:
        return 0
    return data[dataPos+2]

def setAirLevel(level):
    # start_new_thread(setItemValue,('novus300_Level', level,))
    setItemValue(item='novus300_Level', value=level)

def setTemp(itemId, temp):
    setItemValue(item=itemId, value=temp)
    return temp

def setFanLevel(fanId, level):
    temp = ((level / 90 * 7) if level>0 else 0) + 28
    temp = (int(level) * 7 / 90) + 28
    print('novus300_Fan{0}: {1}, Temp: {2}'.format(fanId, int(level), temp))
    setItemValue(item='novus300_Fan{0}'.format(fanId), value=level)
    return level


def getItemValue(item):
    response = requests.get((base_url + '/items/{item}/state').format(item=item))
    return response.content

def setItemValue(item, value):
    requests.put((base_url + '/items/{item}/state').format(item=item), data=str(value))

    #openhab = openHAB(base_url)
    #items = openhab.fetch_all_items()
    #item = items.get(item)
    #item.state = value

    # user = 'openhab'
    # password = '...'
    # command = 'smarthome:update'
    #os.spawnlp(os.P_NOWAIT, '$OPENHAB_RUNTIME/bin/client', '-u', user, '-p', password, command, item, value)
    # os.system('{pathruntime}/bin/client -u {user} -p {password} {command} {item} {value}'.format(pathruntime=os.environ.get('OPENHAB_RUNTIME', '/usr/share/openhab2/runtime'), user=user, password=password, command=command, item=item, value=value))

log = createLogger(os.path.join(logDir, 'novus300.log'), 'novus')
logExt = createLogger(os.path.join(logDir, 'novus300_ext.log'), 'novusExt')

# 
ser = serial.Serial(port, baudrate=baud, timeout=0
                ,stopbits=serial.STOPBITS_ONE,
                parity = serial.PARITY_MARK,
                bytesize=serial.EIGHTBITS
                #rtscts=False,
                #dsrdtr=False
	)

updateOutsideTemp()
readNovus()

ser.close()
