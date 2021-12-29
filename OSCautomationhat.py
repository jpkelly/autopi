#!/usr/bin/python3

import os
from signal import signal, SIGINT
import socket
import argparse
import time
import threading
from threading import Thread
import logging
from systemd import journal

from pythonosc import dispatcher
from pythonosc import osc_server
from pythonosc import udp_client

import automationhat
time.sleep(0.1) # short pause after ads1015 class creation recommended

import systemd_stopper

SERVER_ADDRESS = "0.0.0.0" 			# LISTENING ADDRESS
SERVER_PORT = 7000 					# LISTENING PORT
PRIMARY_ADDRESS = "10.0.0.123" 		# SEND TO PRIMARY
BACKUP_ADDRESS = "172.22.22.108" 	# SEND TO BACKUP
CLIENT_PORT = 8000                  # SEND TO PORT
HBTIMEOUT = 150                     # Heartbeat timeout

HOSTNAME = socket.gethostname()
INPUTSTATE = [0, 0, 0]
ADCSTATE = [0, 0, 0 ,0]
TIMER = 0

print(HOSTNAME)

if automationhat.is_automation_hat():
	automationhat.enable_auto_lights(True) ##### Set to False for better ADC performance
	automationhat.light.power.write(1)
	automationhat.light.comms.write(0)
	automationhat.light.warn.write(0)
	print("Automation Hat library version: " + automationhat.__version__)

log = logging.getLogger('OSC Automation Hat')
log.addHandler(journal.JournaldLogHandler())
log.setLevel(logging.INFO)

def quit_handler(signal_received, frame):
    # Handle any cleanup here
    print('SIGINT or CTRL-C detected.')
    automationhat.light.power.write(0)
    server.shutdown()
    CheckingADC.terminate()
    print('Shutting down OSC server.')
    exit(0)

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
	print("digitalout "+address.split("/")[2]+" handler called")
	log.info("digitalout "+address.split("/")[2]+" handler called")
	relay = int(address.split("/")[2])
	outputstate = int(args[0])
	if automationhat.is_automation_hat():
		if relay == 0:
			automationhat.output[0].write(outputstate)
		if relay == 1:
			automationhat.output[1].write(outputstate)
		if relay == 2:
			automationhat.output[2].write(outputstate)

def restart_handler(address, *args, needs_reply_address=False):
	automationhat.light.comms.write(1)
	print("restart "+address.split("/")[2]+" handler called")
	log.info("restart "+address.split("/")[2]+" handler called")
	restart = int(address.split("/")[2])
	restartstate = int(args[0])
	if automationhat.is_automation_hat():
		if restart == 0:
			print('restart 0 restartstate = ' + str(restartstate))
			if restartstate == 1:
				os.system('sudo reboot')
		if restart == 1:
			print('restart 1 restartstate = ' + str(restartstate))
		if restart == 2:
			print('restart 2 restartstate = ' + str(restartstate))

class ADCchecker:
    def __init__(self):
        self._running = True
    def terminate(self):
        self._running = False
    def run(self):
        # CLIENT 1
        parser_client = argparse.ArgumentParser()
        parser_client.add_argument("--ip", default=PRIMARY_ADDRESS,
                help="The ip of the OSC server")
        parser_client.add_argument("--port", type=int, default=CLIENT_PORT,
                help="The port the OSC server is listening on")
        args_client = parser_client.parse_args()
        client = udp_client.SimpleUDPClient(args_client.ip, args_client.port)
        log.info("Sending to OSC host "+PRIMARY_ADDRESS)
        # CLIENT 2
        parser_client = argparse.ArgumentParser()
        parser_client.add_argument("--ip", default=BACKUP_ADDRESS,
                help="The ip of the OSC server")
        parser_client.add_argument("--port", type=int, default=CLIENT_PORT,
                help="The port the OSC server is listening on")
        args_client = parser_client.parse_args()
        client2 = udp_client.SimpleUDPClient(args_client.ip, args_client.port)
        log.info("Sending to OSC host "+BACKUP_ADDRESS)
        # ADC CHECKING ROUTINE
        while self._running:
            i = 0
            while (i < 3): # SEND ADC STATES
                ADCVALUE = (automationhat.analog[i].read())
                if (ADCSTATE[i] != ADCVALUE):
                    ADCSTATE[i] = ADCVALUE
                    try:
                        automationhat.light.comms.write(0.1)
                        log.info("Sending to "+PRIMARY_ADDRESS+" /" + HOSTNAME + "/A"+str(i+1)+" "+str(ADCSTATE[i]))
                        print("Sending OSC to "+PRIMARY_ADDRESS+" /" + HOSTNAME + "/A"+str(i+1)+" "+str(ADCSTATE[i]))
                        client.send_message("/" + HOSTNAME + "/A"+str(i+1), str(ADCSTATE[i]))
                        automationhat.light.comms.write(0.3)
                        automationhat.light.warn.write(0)
                    except:
                        print("host "+PRIMARY_ADDRESS+" not found")
                        log.info("host "+PRIMARY_ADDRESS+" not found")
                        automationhat.light.comms.write(0)
                        automationhat.light.warn.write(1)
                i = i + 1

# THREADING SETUP
CheckingADC = ADCchecker()                          # Instance Class
CheckingADCThread = Thread(target=CheckingADC.run)	# Create Thread
CheckingADCThread.start()                           # Start Thread

# SERVER SETUP
print("Starting OSC server...")
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
dispatcher.map("/restart/0", restart_handler)
dispatcher.map("/restart/1", restart_handler)
dispatcher.map("/restart/2", restart_handler)

server = osc_server.ThreadingOSCUDPServer(
        (args_server.ip, args_server.port), dispatcher)
print("Listening on {}".format(server.server_address))
log.info("OSC server started on {}".format(server.server_address))
server_thread = threading.Thread(target=server.serve_forever)
server_thread.start()

stopper = systemd_stopper.install('USR1', 'HUP')

while stopper.run:
    signal(SIGINT, quit_handler)
    # print("RUNNING")
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
    parser_client.add_argument("--ip", default=BACKUP_ADDRESS,
            help="The ip of the OSC server")
    parser_client.add_argument("--port", type=int, default=CLIENT_PORT,
            help="The port the OSC server is listening on")
    args_client = parser_client.parse_args()
    client2 = udp_client.SimpleUDPClient(args_client.ip, args_client.port)
    log.info("Sending to OSC host "+BACKUP_ADDRESS)

    # # CHECK ANALOG INPUT PINS  ###### DISABLED BECAUSE THREADING IS USED  ######
    # i = 0
    # while (i < 3): # SEND ADC STATES
    #     ADCVALUE = (automationhat.analog[i].read())
    #     if (ADCSTATE[i] != ADCVALUE):
    #         ADCSTATE[i] = ADCVALUE
    #         try:
    #             automationhat.light.comms.write(0.1)
    #             log.info("Sending to "+PRIMARY_ADDRESS+" /" + HOSTNAME + "/A"+str(i+1)+" "+str(ADCSTATE[i]))
    #             print("Sending OSC to "+PRIMARY_ADDRESS+" /" + HOSTNAME + "/A"+str(i+1)+" "+str(ADCSTATE[i]))
    #             client.send_message("/" + HOSTNAME + "/A"+str(i+1), str(ADCSTATE[i]))
    #             automationhat.light.comms.write(0.3)
    #             automationhat.light.warn.write(0)
    #         except:
    #             print("host "+PRIMARY_ADDRESS+" not found")
    #             log.info("host "+PRIMARY_ADDRESS+" not found")
    #             automationhat.light.comms.write(0)
    #             automationhat.light.warn.write(1)
    #     i = i + 1

    # CHECK DIGITAL INPUT PINS
    i = 0
    while (i < 3):
        # print("checking input pin " + str(i))
        INPUTVALUE = (automationhat.input[i].read())
        if (INPUTSTATE[i] != INPUTVALUE):
            INPUTSTATE[i] = INPUTVALUE
            print ("INPUT"+str(i+1)+" = "+str(INPUTSTATE[i]))
            log.info("INPUT"+str(i+1)+" = "+str(INPUTSTATE[i]))
            TIMER = HBTIMEOUT
            try:
                automationhat.light.comms.write(0.1)
                log.info("Sending OSC to "+PRIMARY_ADDRESS+"/" + HOSTNAME + "/DI"+str(i+1)+" "+str(INPUTVALUE))
                print("Sending OSC to "+PRIMARY_ADDRESS+"/" + HOSTNAME + "/DI"+str(i+1)+" "+str(INPUTVALUE))
                client.send_message("/" + HOSTNAME + "/DI"+str(i+1), INPUTVALUE)
                automationhat.light.comms.write(0.5)
                automationhat.light.warn.write(0)
            except Exception as e:
                print('Error sending OSC: '+ str(e))
                log.info('Error sending OSC: '+ str(e))
                automationhat.light.comms.write(0)
                automationhat.light.warn.write(1)
        i = i + 1

    # HEARTBEAT TIMER
    # print("TIMER = " + str(TIMER))
    if TIMER <= HBTIMEOUT:
        TIMER = TIMER + 1
    else:
        try:
            automationhat.light.comms.write(0.1)
            print(HOSTNAME + ' HEARTBEAT')
            client.send_message("/" + HOSTNAME + "/heartbeat", [1])
            automationhat.light.comms.write(0.3)
            # automationhat.light.warn.write(0)
        except:
            print("host "+PRIMARY_ADDRESS+" not found")
            automationhat.light.comms.write(0)
            automationhat.light.warn.write(1)
        TIMER = 0

print("Shutting down jPio...")
log.info("Shutting down jPio...")
automationhat.light.power.write(0)
server.shutdown()
CheckingADC.terminate()
print("OSC server shut down")
log.info("OSC server shut down")
