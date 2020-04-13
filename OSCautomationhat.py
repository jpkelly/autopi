#!/usr/bin/python3
import argparse
import math
import time
import threading
import logging
from systemd import journal

from pythonosc import dispatcher
from pythonosc import osc_server
from pythonosc import osc_message_builder
from pythonosc import udp_client

import automationhat
time.sleep(0.1) # short pause after ads1015 class creation recommended

import systemd_stopper

from threading import Thread

SERVER_ADDRESS = "0.0.0.0" # LISTENING ADDRESS
SERVER_PORT = 7110
PRIMARY_ADDRESS = "172.22.22.107" # SEND TO ADDRESS
BACKUP_ADDRESS = "172.22.22.108"
CLIENT_PORT = 7112
INPUTSTATE = [0, 0, 0]
ADCSTATE = [0, 0, 0 ,0]
TIMER = 0
TIMER2 = 0

if automationhat.is_automation_hat():
	automationhat.light.power.write(1)
	automationhat.light.comms.write(0)
	automationhat.light.warn.write(0)
	print("Automation Hat library version: " + automationhat.__version__)

log = logging.getLogger('OSC Automation Hat')
log.addHandler(journal.JournaldLogHandler())
log.setLevel(logging.INFO)

def relay_handler(address, *args, needs_reply_address=False):
	automationhat.light.comms.write(1)
	print("relay "+address.split("/")[2]+" handler called")
	log.info("relay "+address.split("/")[2]+" handler called")
	relay = int(address.split("/")[2])
	relaystate = int(args[0])
	if automationhat.is_automation_hat():
		if relay == 0:
			automationhat.relay[0].write(relaystate)
		if relay == 1:
			automationhat.relay[1].write(relaystate)
		if relay == 2:
			automationhat.relay[2].write(relaystate)

def led_handler(address, *args, needs_reply_address=False):
	automationhat.light.comms.write(1)
	print("LED "+address.split("/")[2]+" handler called")
	log.info("LED "+address.split("/")[2]+" handler called")
	led = int(address.split("/")[2])
	ledstate = int(args[0])
	if automationhat.is_automation_hat():
		if led == 0:
			automationhat.light.power.write(ledstate)
		if led == 1:
			automationhat.light.comms.write(ledstate)
		if led == 2:
			automationhat.light.warn.write(ledstate)

def output_handler(address, *args, needs_reply_address=False):
	automationhat.light.comms.write(1)
	print("relay "+address.split("/")[2]+" handler called")
	log.info("relay "+address.split("/")[2]+" handler called")
	relay = int(address.split("/")[2])
	outputstate = int(args[0])
	if automationhat.is_automation_hat():
		if relay == 0:
			automationhat.output[0].write(outputstate)
		if relay == 1:
			automationhat.output[1].write(outputstate)
		if relay == 2:
			automationhat.output[2].write(outputstate)

class ADCchecker:
	def __init__(self):
		self._running = True

	def terminate(self):
		self._running = False

	def run(self):
		# CLIENT
		parser_client = argparse.ArgumentParser()
		parser_client.add_argument("--ip", default=PRIMARY_ADDRESS,
				help="The ip of the OSC server")
		parser_client.add_argument("--port", type=int, default=CLIENT_PORT,
				help="The port the OSC server is listening on")
		args_client = parser_client.parse_args()

		client = udp_client.SimpleUDPClient(args_client.ip, args_client.port)
		log.info("Sending to OSC host "+PRIMARY_ADDRESS)
		while self._running:
			i = 0
			while (i < 3):
				ADCvalue = (automationhat.analog[i].read())
				if ((ADCSTATE[i] >= (ADCvalue + 1)) or (ADCSTATE[i] <= (ADCvalue - 1))):
					print("ADC "+str(i)+" SAVED: "+ str(ADCSTATE[i]))
					print("ADC "+str(i)+" READ: "+ str(ADCvalue))
					print()
					ADCSTATE[i] = ADCvalue
					log.info("ADC "+str(i+1)+" = "+str(ADCvalue))
					try:
						automationhat.light.comms.write(0.1)
						log.info("Sending OSC to "+PRIMARY_ADDRESS+": /adc/"+str(i+1)+" "+str(ADCvalue))
						print("Sending OSC to "+PRIMARY_ADDRESS+": /adc/"+str(i+1)+" "+str(ADCvalue))
						client.send_message("/adc/"+str(i+1), ADCvalue)
						log.info("success")
						automationhat.light.comms.write(0.5)
						automationhat.light.warn.write(0)
					except Exception as e:
						print('Error sending OSC: '+ str(e))
						log.info('Error sending OSC: '+ str(e))
						automationhat.light.comms.write(0)
						automationhat.light.warn.write(1)
				i = i + 1

# THREADING SETUP
CheckingADC = ADCchecker()													#Create Class
CheckingADCThread = Thread(target=CheckingADC.run)	#Create Thread
CheckingADCThread.start()														#Start Thread

if __name__ == "__main__":

	stopper = systemd_stopper.install()
	while stopper.run:
		# SERVER SETUP
		print("Starting server...")
		parser_server = argparse.ArgumentParser()
		parser_server.add_argument("--ip",
				default=SERVER_ADDRESS, help="The ip to listen on")
		parser_server.add_argument("--port",
				type=int, default=SERVER_PORT, help="The port to listen on")
		args_server = parser_server.parse_args()

		dispatcher = dispatcher.Dispatcher()
		dispatcher.map("/relay/0", relay_handler)
		dispatcher.map("/relay/1", relay_handler)
		dispatcher.map("/relay/2", relay_handler)
		dispatcher.map("/led/0", led_handler)
		dispatcher.map("/led/1", led_handler)
		dispatcher.map("/led/2", led_handler)
		dispatcher.map("/output/0", output_handler)
		dispatcher.map("/output/1", output_handler)
		dispatcher.map("/output/2", output_handler)

		server = osc_server.ThreadingOSCUDPServer(
				(args_server.ip, args_server.port), dispatcher)
		print("Server started on {}".format(server.server_address))
		log.info("OSC server started on {}".format(server.server_address))
		server_thread = threading.Thread(target=server.serve_forever)
		server_thread.start()

		# CLIENT SETUP
		parser_client = argparse.ArgumentParser()
		parser_client.add_argument("--ip", default=PRIMARY_ADDRESS,
				help="The ip of the OSC server")
		parser_client.add_argument("--port", type=int, default=CLIENT_PORT,
				help="The port the OSC server is listening on")
		args_client = parser_client.parse_args()
		client = udp_client.SimpleUDPClient(args_client.ip, args_client.port)
		log.info("Sending to OSC host "+PRIMARY_ADDRESS)

		parser_client = argparse.ArgumentParser()
		parser_client.add_argument("--ip", default=PRIMARY_ADDRESS,
				help="The ip of the OSC server")
		parser_client.add_argument("--port", type=int, default=CLIENT_PORT,
				help="The port the OSC server is listening on")
		args_client = parser_client.parse_args()
		client2 = udp_client.SimpleUDPClient(args_client.ip, args_client.port)
		log.info("Sending to OSC host "+BACKUP_ADDRESS)

		while stopper.run:
			# HEARTBEAT TIMER
			if TIMER <= 5000:
				TIMER = TIMER + 1
				# print(TIMER)
			else:
				TIMER = 0
				i = 0
				while (i < 3): # SEND INPUT STATES
					INPUTSTATE[i] = automationhat.input[i].read()
					print ("INPUT "+str(i+1)+" HEARTBEAT = "+str(INPUTSTATE[i]))
					log.info("INPUT "+str(i+1)+" HEARTBEAT = "+str(INPUTSTATE[i]))
					try:
						automationhat.light.comms.write(0.1)
						log.info("Sending to "+PRIMARY_ADDRESS+" OSC: /input/"+str(i+1)+" "+str(INPUTSTATE[i]))
						client.send_message("/input/"+str(i+1), INPUTSTATE[i])
						log.info("success")
						automationhat.light.comms.write(0.3)
						automationhat.light.warn.write(0)
					except:
						print("host "+PRIMARY_ADDRESS+" not found")
						log.info("host "+PRIMARY_ADDRESS+" not found")
						automationhat.light.comms.write(0)
						automationhat.light.warn.write(1)
					# SEND TO BACKUP
					try:
						automationhat.light.comms.write(0.1)
						log.info("Sending to "+BACKUP_ADDRESS+" OSC: /input/"+str(i+1)+" "+str(INPUTSTATE[i]))
						client2.send_message("/input/"+str(i+1), INPUTSTATE[i])
						log.info("success")
						automationhat.light.comms.write(0.3)
						automationhat.light.warn.write(0)
					except:
						print("host "+BACKUP_ADDRESS+" not found")
						log.info("host "+BACKUP_ADDRESS+" not found")
						automationhat.light.comms.write(0)
						automationhat.light.warn.write(1)
					i = i + 1
				i = 0
				# while (i < 3): # SEND ADC STATES
				# 	ADCSTATE[i] = (automationhat.analog[i].read())
				# 	print ("ADC "+str(i+1)+" HEARTBEAT = "+str(ADCSTATE[i]))
				# 	log.info("ADC "+str(i+1)+" HEARTBEAT = "+str(ADCSTATE[i]))
				# 	try:
				# 		automationhat.light.comms.write(0.1)
				# 		log.info("Sending to "+PRIMARY_ADDRESS+" OSC: /heartbeat/adc/"+str(i+1)+" "+str(ADCSTATE[i]))
				# 		client.send_message("/heartbeat/adc/"+str(i+1), ADCSTATE[i])
				# 		log.info("success")
				# 		automationhat.light.comms.write(0.3)
				# 		automationhat.light.warn.write(0)
				# 	except:
				# 		print("host "+PRIMARY_ADDRESS+" not found")
				# 		log.info("host "+PRIMARY_ADDRESS+" not found")
				# 		automationhat.light.comms.write(0)
				# 		automationhat.light.warn.write(1)
				# 	i = i + 1

			# CHECK INPUT PINS
			i = 0
			while (i < 3):
				# print("checking input pin " + str(i))
				INPUTvalue = (automationhat.input[i].read())
				if (INPUTSTATE[i] != INPUTvalue):
					INPUTSTATE[i] = INPUTvalue
					print ("INPUT"+str(i+1)+" = "+str(INPUTSTATE[i]))
					log.info("INPUT"+str(i+1)+" = "+str(INPUTSTATE[i]))
					TIMER = 5000
					# try:
					# 	automationhat.light.comms.write(0.1)
					# 	log.info("Sending OSC to "+PRIMARY_ADDRESS+": /input/"+str(i+1)+" "+str(INPUTvalue))
					# 	print("Sending OSC to "+PRIMARY_ADDRESS+": /input/"+str(i+1)+" "+str(INPUTvalue))
					# 	client.send_message("/input/"+str(i+1), INPUTvalue)
					# 	log.info("success")
					# 	automationhat.light.comms.write(0.5)
					# 	automationhat.light.warn.write(0)
					# except Exception as e:
					# 	print('Error sending OSC: '+ str(e))
					# 	log.info('Error sending OSC: '+ str(e))
					# 	automationhat.light.comms.write(0)
					# 	automationhat.light.warn.write(1)
				i = i + 1

	print("Shutting down autoPi...")
	log.info("Shutting down autoPi...")
	automationhat.light.power.write(0)
	server.shutdown()
	print("OSC server shut down")
	log.info("OSC server shut down")
	CheckingADC.terminate()
