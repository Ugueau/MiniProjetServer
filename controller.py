# Program to control passerelle between Android application
# and micro-controller through USB tty
import time
import argparse
import signal
import sys
import socket
import socketserver
import serial
import threading
import json
import queue

HOST           = "0.0.0.0"
UDP_PORT       = 10000
MICRO_COMMANDS = ["TL" , "LT"]
FILENAME        = "values.txt"
LAST_VALUE      = "LA FRANCE !"

notification_queue = queue.Queue()

class ThreadedUDPRequestHandler(socketserver.BaseRequestHandler):

    def handle(self):
        data = self.request[0].strip()
        socket = self.request[1]
        current_thread = threading.current_thread()
        print("{}: client: {}, wrote: {}".format(current_thread.name, self.client_address, data))
        try:
                message = data.decode("utf-8")  # decode bytes to string
        except UnicodeDecodeError:
                print("Failed to decode message from client")
                return
        if data != "":
                        if message in MICRO_COMMANDS: # Send message through UART
                                sendUARTMessage(data)
                        elif message == "getValues()": # Sent last value received from micro-controller
                                socket.sendto(LAST_VALUE, self.client_address) 
                                # TODO: Create last_values_received as global variable      
                        elif message == "is_reachable":
                                socket.sendto(b"1", self.client_address)
                        elif message == "get_microbits":
                                with open('microbits_configuration.json', 'r') as file:
                                        sensor_data = json.load(file)
                                        sensor_data = json.dumps(sensor_data)
                                        response = sensor_data.encode('utf-8')
                                        socket.sendto(response, self.client_address)
                        elif message[:15] == "configuration :":
                                json_part = message.split(":", 1)[1].strip()
                                data = json.loads(json_part)
                                #Notify Serial thread
                                notification_queue.put(("configuration_update", data))
                                
                                with open('microbits_configuration.json', 'r') as file:
                                        sensor_data = json.load(file)
                                for sensor in sensor_data:
                                        if sensor["id"] == data["id"]:
                                                sensor.update(data)
                                                break
                                with open('microbits_configuration.json', 'w') as file:
                                        json.dump(sensor_data, file, indent=2)
                                                        
                        else:
                                print("Unknown message: ",data)

class ThreadedUDPServer(socketserver.ThreadingMixIn, socketserver.UDPServer):
    pass


# send serial message 
SERIALPORT = "/dev/ttyUSB0"
BAUDRATE = 115200
ser = serial.Serial()

def initUART():        
        # ser = serial.Serial(SERIALPORT, BAUDRATE)
        ser.port=SERIALPORT
        ser.baudrate=BAUDRATE
        ser.bytesize = serial.EIGHTBITS #number of bits per bytes
        ser.parity = serial.PARITY_NONE #set parity check: no parity
        ser.stopbits = serial.STOPBITS_ONE #number of stop bits
        ser.timeout = None          #block read

        # ser.timeout = 0             #non-block read
        # ser.timeout = 2              #timeout block read
        ser.xonxoff = False     #disable software flow control
        ser.rtscts = False     #disable hardware (RTS/CTS) flow control
        ser.dsrdtr = False       #disable hardware (DSR/DTR) flow control
        #ser.writeTimeout = 0     #timeout for write
        print('Starting Up Serial Monitor')
        try:
                ser.open()
        except serial.SerialException:
                print("Serial {} port not available".format(SERIALPORT))
                exit()



def sendUARTMessage(msg):
    ser.write(msg.encode())
    print("Message <" + msg + "> sent to micro-controller." )


# Main program logic follows:
if __name__ == '__main__':
        # Check for IP address passed as the first parameter
        if len(sys.argv) > 1:
                HOST = sys.argv[1]
                print(f"Using IP address: {HOST}")
        else:
                print("No IP address provided. Using default: 0.0.0.0")
        # initUART()
        f= open(FILENAME,"a")
        print ('Press Ctrl-C to quit.')

        server = ThreadedUDPServer((HOST, UDP_PORT), ThreadedUDPRequestHandler)

        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True

        try:
                server_thread.start()
                print("Server started at {} port {}".format(HOST, UDP_PORT))
                while True: 
                        if ser.isOpen():
                        # time.sleep(100)
                                if (ser.inWaiting() > 0): # if incoming bytes are waiting 
                                        data_bytes = ser.read(ser.inWaiting())
                                        data_str = data_bytes.decode()
                                        f.write(data_str)
                                        LAST_VALUE = data_str
                                        print(data_str)
                        try:
                                notification_type, payload = notification_queue.get_nowait()
                                if notification_type == "configuration_update":
                                        sendUARTMessage(payload)
                        except queue.Empty:
                                pass
                        
        except (KeyboardInterrupt, SystemExit):
                print("Crash Exiting...")
                server.shutdown()
                server.server_close()
                f.close()
                ser.close()
                exit()
