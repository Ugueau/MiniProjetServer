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

HOST = "0.0.0.0"
UDP_PORT = 10000
MICRO_COMMANDS = ["TL", "LT"]
FILENAME = "values.txt"
LAST_VALUE = "LA FRANCE !"

notification_queue = queue.Queue()


class ThreadedUDPRequestHandler(socketserver.BaseRequestHandler):

    def handle(self):
        data = self.request[0].strip()
        socket = self.request[1]
        current_thread = threading.current_thread()
        print(
            "{}: client: {}, wrote: {}".format(
                current_thread.name, self.client_address, data
            )
        )
        try:
            message = data.decode("utf-8")  # decode bytes to string
        except UnicodeDecodeError:
            print("Failed to decode message from client")
            return
        if data != "":
            if message in MICRO_COMMANDS:  # Send message through UART
                sendUARTMessage(data)
            elif (
                message == "getValues()"
            ):  # Sent last value received from micro-controller
                socket.sendto(LAST_VALUE, self.client_address)
                # TODO: Create last_values_received as global variable
            elif message == "is_reachable":
                socket.sendto(b"1", self.client_address)
            elif message == "get_microbits":
                with open("microbits_configuration.json", "r") as file:
                    sensor_data = json.load(file)
                    sensor_data = json.dumps(sensor_data)
                    response = sensor_data.encode("utf-8")
                    socket.sendto(response, self.client_address)
            elif message[:15] == "configuration :":
                json_part = message.split(":", 1)[1].strip()
                data = json.loads(json_part)
                with open("microbits_configuration.json", "r") as file:
                    sensor_data = json.load(file)
                for sensor in sensor_data:
                    if sensor["id"] == data["id"]:
                        sensor["luminosityConfigIndex"] = data["luminosityConfigIndex"]
                        sensor["temperatureConfigIndex"] = data[
                            "temperatureConfigIndex"
                        ]
                        sensor["humidityConfigIndex"] = data["humidityConfigIndex"]
                with open("microbits_configuration.json", "w") as file:
                    json.dump(sensor_data, file, indent=2)
                # Notify Serial thread
                notification_queue.put(("configuration_update", data))
            else:
                print("Unknown message: ", data)


class ThreadedUDPServer(socketserver.ThreadingMixIn, socketserver.UDPServer):
    pass


# send serial message
SERIALPORT = "COM5"
BAUDRATE = 115200
ser = serial.Serial()


def initUART():
    # ser = serial.Serial(SERIALPORT, BAUDRATE)
    ser.port = SERIALPORT
    ser.baudrate = BAUDRATE
    ser.bytesize = serial.EIGHTBITS  # number of bits per bytes
    ser.parity = serial.PARITY_NONE  # set parity check: no parity
    ser.stopbits = serial.STOPBITS_ONE  # number of stop bits
    ser.timeout = None  # block read

    # ser.timeout = 0             #non-block read
    # ser.timeout = 2              #timeout block read
    ser.xonxoff = False  # disable software flow control
    ser.rtscts = False  # disable hardware (RTS/CTS) flow control
    ser.dsrdtr = False  # disable hardware (DSR/DTR) flow control
    # ser.writeTimeout = 0     #timeout for write
    print("Starting Up Serial Monitor")
    try:
        ser.open()
    except serial.SerialException:
        print("Serial {} port not available".format(SERIALPORT))
        exit()


def getConfigString(message):
    config_indices = [
        (message["temperatureConfigIndex"], "T"),
        (message["humidityConfigIndex"], "H"),
        (message["luminosityConfigIndex"], "L"),
    ]
    config_indices.sort(key=lambda x: x[0])
    config_string = "".join([letter for index, letter in config_indices])
    return config_string


def writeUartMessage(data):
    parts = data.split("-")
    if len(parts) == 5:
        received_id = parts[0]
        temperature = int(float(parts[2]))
        luminosity = int(parts[3])
        humidity = int(float(parts[4]))

        with open("microbits_configuration.json", "r") as file:
            sensor_data = json.load(file)

        display_config = "TLH"
        found = False
        for microbit in sensor_data:
            if microbit["id"] == received_id:
                # Mettre à jour les valeurs du JSON
                microbit["temperature"] = temperature
                microbit["luminosity"] = luminosity
                microbit["humidity"] = humidity
                found = True
                display_config = getConfigString(microbit)
                break

        if not found:
            new_microbit = {
                "name": "Microbit " + received_id,
                "id": received_id,
                "temperature": temperature,
                "humidity": humidity,
                "luminosity": luminosity,
                "temperatureConfigIndex": 0,
                "humidityConfigIndex": 2,
                "luminosityConfigIndex": 1,
            }
            sensor_data.append(new_microbit)
        with open("microbits_configuration.json", "w") as file:
            json.dump(sensor_data, file, indent=2)
        return display_config


def read_until_newline(ser):
    data_bytes = b""
    while True:
        byte = ser.read(1)
        if not byte:
            break  # Si aucun byte n'est lu, sortir de la boucle
        data_bytes += byte
        if byte == b"\n":
            break  # Si un caractère de nouvelle ligne est rencontré, sortir de la boucle
    return data_bytes.decode()


# Main program logic follows:
if __name__ == "__main__":
    # Check for IP address passed as the first parameter
    if len(sys.argv) > 1:
        HOST = sys.argv[1]
        print(f"Using IP address: {HOST}")
    else:
        print("No IP address provided. Using default: 0.0.0.0")
    initUART()
    f = open(FILENAME, "a")
    print("Press Ctrl-C to quit.")

    server = ThreadedUDPServer((HOST, UDP_PORT), ThreadedUDPRequestHandler)

    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True

    try:
        server_thread.start()
        print("Server started at {} port {}".format(HOST, UDP_PORT))
        while True:
            if ser.isOpen():
                # time.sleep(100)
                if ser.inWaiting() > 0:  # if incoming bytes are waiting
                    data_str = read_until_newline(ser)
                    # data_bytes = ser.read(ser.inWaiting())
                    #     data_str = data_bytes.decode()
                    f.write(data_str)
                    LAST_VALUE = data_str
                    print(data_str)
                    display_string = writeUartMessage(data_str) + "\n"
                    print(display_string)
                    ser.write(display_string.encode())
            try:
                notification_type, payload = notification_queue.get_nowait()
                if notification_type == "configuration_update":
                    print(getConfigString(payload))
            except queue.Empty:
                pass

    except (KeyboardInterrupt, SystemExit):
        print("Crash Exiting...")
        server.shutdown()
        server.server_close()
        f.close()
        ser.close()
        exit()
