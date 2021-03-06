#!/usr/bin/env python

#Control center for Peripheral Sensing Node
#Author: Kevin Murphy
#Date  : 28 - Febuary - 15

import json
import time
import datetime
import socket
import struct
from uuid import getnode as get_mac
import threading 
import pyupm_grove as grove
import pyupm_buzzer as upmBuzzer
import pyupm_ttp223 as ttp223

#Grove Pins
PIN_TEMP   = 0
PIN_LIGHT  = 1
PIN_LED    = 2
PIN_BUZZER = 3
PIN_TOUCH  = 4

#Sensor Names
SENSOR_TEMP  = "temperature"
SENSOR_LIGHT = "light"
SENSOR_TOUCH = "touch"

#Sensor Objects
temp   = None
light  = None
buzzer = None
touch  = None
led    = None

#SOCKET
MULTICAST_GRP  = '224.1.1.1'
MULTICAST_PORT = 5007
DEFAULT_PORT   = 5006
DEFAULT_SERVER_PORT = 5005
piIPAddress = ""


#Session Keys
SESSION_IP        = "ip_address"
SESSION_TIMESTAMP = "time_stamp"
SESSION_DEVICE_ID = "device_id" 
SESSION_TYPE      = "type"

#Wifi Direct 
JSON_KEY_WIFI_DIRECT_SERVICE = "service"
JSON_KEY_WIFI_DIRECT_PAYLOAD = "payload"
SERVICE_CONNECT = "connect"
SERVICE_PAIRED  = "paired"
JSON_VALUE_WIFI_DIRECT_CURRENT_PERIPHERAL_SENSOR_VALUES = "peripheral_sensor_values"
SERVICE_FlASH_LED = "flash_led"

#Buzzer Notes
chords = [upmBuzzer.DO, upmBuzzer.RE, upmBuzzer.MI, upmBuzzer.FA, 
          upmBuzzer.SOL, upmBuzzer.LA, upmBuzzer.SI, upmBuzzer.DO, 
          upmBuzzer.SI]

"""
JSON serializer for objects not serializable by default json code.
Required as the datetime object won't serialize by default.
"""
def json_serial(obj):
    from datetime import datetime
    from decimal import Decimal

    if isinstance(obj, datetime):
        serial = obj.isoformat()
        return serial 

    if isinstance(obj, Decimal):
        return int(float(obj)) 

def main():
	global piIPAddress
	connectedToPi  = False
	createSensors()
	session  = createSession()

	while not connectedToPi:
		connectedToPi = connectToPi(session, createSocket(session[SESSION_IP], None))

	print "Starting Send Thread"
	sendThread  = threading.Thread(target=sendSensorValues,args=(session,))
	sendThread.setDaemon(True)
	sendThread.start()

	print "Starting Recieve Thread"
	recieveThread  = threading.Thread(target=recievePacketFromPi,args=(session,))
	recieveThread.setDaemon(True)
	recieveThread.start()


#SOCKET AND CONNECTION STUFF
def createPacket(service, payload):
	_packet  = {}
	_payload = {}

	_packet[JSON_KEY_WIFI_DIRECT_SERVICE] = service 
	_payload[service] = payload
	_packet[JSON_KEY_WIFI_DIRECT_PAYLOAD] = _payload
	return _packet

def createSocket(bindToIP, connectToIP):
	newSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	newSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	newSocket.setblocking(True)

	if bindToIP is not None:
		#For receiving 
		newSocket.bind((bindToIP, DEFAULT_PORT))
		newSocket.listen(5)
	elif connectToIP is not None:
		#For sending
		newSocket.connect((connectToIP, DEFAULT_SERVER_PORT))

	return newSocket

def sendPacketToPi(packet):
	global piIPAddress
	if piIPAddress != "":
		try:
			print "Sending Sensor Values to Pi"
			packetString = json.dumps(packet, default=json_serial)
			print packetString
			piSendSocket = createSocket(bindToIP=None, connectToIP=piIPAddress)
			piSendSocket.send(packetString)
			piSendSocket.close()
		except:
			print "RaspPi Refused Connection, trying reconnect in 10 seconds"
			connectedToPi = False
			while not connectedToPi:
				time.sleep(10)
				session = createSession()
				connectedToPi = connectToPi(session=session, piRecieveSocket=createSocket(session[SESSION_IP], None))


def recievePacketFromPi(session):
	piRecieveSocket = createSocket(bindToIP=session[SESSION_IP], connectToIP=None)
	while True:
		conn, addr = piRecieveSocket.accept()
		print "Waiting to Recieve Packet from Pi"
		rawPacket  = conn.recv(1024)
		print rawPacket
		try:
			packet  = json.loads(rawPacket)
			try:
				serivce = packet[JSON_KEY_WIFI_DIRECT_SERVICE]
				if serivce == SERVICE_FlASH_LED:
					flashLed(led)
			except KeyError:
				print "Recieve Packet From Pi -> KeyError Thrown"
		except ValueError:
			print "Unable to Decode JSON Object"


def sendSensorValues(session):
    while True:
		sensorReadings = {}
		sensorReadings[SENSOR_TOUCH]      = checkTouchPressed(touch)
		sensorReadings[SENSOR_TEMP]       = readTemperature(temp)
		sensorReadings[SENSOR_LIGHT]      = readLightLevel(light)
		sensorReadings[SESSION_TIMESTAMP] = datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')
		sensorReadings[SESSION_DEVICE_ID] = session[SESSION_DEVICE_ID]
		sensorPacket = createPacket(service=JSON_VALUE_WIFI_DIRECT_CURRENT_PERIPHERAL_SENSOR_VALUES, payload=sensorReadings)
		sendPacketToPi(sensorPacket)
		time.sleep(10)	

def connectToPi(session, piRecieveSocket):
	global piIPAddress
	connected = False
	#Connect via Multicast Channel
	multicastSocket = createMulticatSocket(session[SESSION_IP], MULTICAST_GRP, MULTICAST_PORT)
	connectPacket = { JSON_KEY_WIFI_DIRECT_SERVICE : SERVICE_CONNECT, JSON_KEY_WIFI_DIRECT_PAYLOAD : { "session" : session}}
	multicastSocket.sendto(json.dumps(connectPacket), (MULTICAST_GRP, MULTICAST_PORT))
	multicastSocket.close()
	#Create Socket and wait for ack -> {'payload': {'paired': {'status_code': 200}}, 'service': 'paired'}
	conn, addr = piRecieveSocket.accept()
	rawPacket  = conn.recv(1024)
	try:
		packet = json.loads(rawPacket)
		if packet[JSON_KEY_WIFI_DIRECT_SERVICE] == SERVICE_PAIRED and packet[JSON_KEY_WIFI_DIRECT_PAYLOAD][SERVICE_PAIRED]['status_code'] == 200:
			piIP, piPortNo = conn.getpeername()
			piIPAddress = piIP
			connected = True
			print "Connect to RaspPi :: IP ->", piIPAddress
			return connected
	except ValueError:
		print "ValueError :: Unable to Encode Json Object"
	

def createSession():
	timestamp   = datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')
	ipAddress   = getIPAddress()
	mac_address = get_mac()
	sess = { SESSION_IP: ipAddress, SESSION_DEVICE_ID : mac_address, SESSION_TIMESTAMP : timestamp, SESSION_TYPE : "peripheral" } 
	json.dumps(sess)
	return sess

def getIPAddress():
	try:
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		s.connect(("192.168.42.1",80))
		myIP = s.getsockname()[0]
		print "My IP : ", myIP
		return myIP
	except:
		print "Unable to get IP Address, Retrying in 10 Seconds"
		time.sleep(10)
		getIPAddress()

def createMulticatSocket(inetIP, multicastGroup, multicastPort):
	multicastSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
	multicastSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	#Socket must be connected to the wlan0 interface's IP address
	#Bind to our default Multicast Port.
	multicastSocket.bind((multicastGroup, multicastPort))
	mreq = struct.pack("4sl", socket.inet_aton(multicastGroup), socket.INADDR_ANY)
	multicastSocket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
	#multicastSocket.setblocking(True)	
	return multicastSocket

#SENSORS----------------------
def createSensors():
	global temp, light, buzzer, touch, led

	print "Created Sensors ::"
	temp = grove.GroveTemp(PIN_TEMP)
	print temp.name()

	light = grove.GroveLight(PIN_LIGHT)
	print light.name()

	buzzer = upmBuzzer.Buzzer(PIN_BUZZER)
	print buzzer.name()

	touch = ttp223.TTP223(PIN_TOUCH)
	print touch.name()

	led = grove.GroveLed(PIN_LED)
	print led.name()

def soundBuzzer(buzzer):
	global chords
	buzzer.playSound(chords[0], 1000000)

def checkTouchPressed(touch):
	isPressed = False
	if touch.isPressed():
		isPressed = True
	return isPressed

def readTemperature(temp):
	return temp.value()

def readLightLevel(light):
	return light.raw_value()

def flashLed(led):
	led.on()
	time.sleep(1)
	led.off()
	time.sleep(1)

try:
    main()
    while True:
	time.sleep(1)


except KeyboardInterrupt, SystemExit:
    print "KeyboardInterrupted..."
    del temp
    del light
    del touch
    del buzzer
    del led


