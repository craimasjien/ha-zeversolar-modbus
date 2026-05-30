Context for LLM: Home Assistant Custom Component for Zeversolar (Eversolar Protocol) via TCP
Objective:
Develop a Home Assistant custom_component that reads real-time solar data from a Zeversolar 2000s inverter and creates sensor entities (e.g., Current Power, Daily Energy, Total Energy).

Hardware Setup:

Inverter: Zeversolar 2000s (Zeverlution series).

Bridge: Waveshare RS485-to-Ethernet converter.

Configuration: The Waveshare is configured as a "TCP Server" (IP: 192.168.2.200, Port: 4196 or 502) passing raw serial data. No Modbus TCP-to-RTU translation is enabled on the hardware.

The Core Problem:
The Zeversolar inverter does not speak standard Modbus RTU over its RS485 port. Therefore, Home Assistant's native Modbus integration cannot be used. Instead, the inverter uses a proprietary serial protocol (often referred to in the community as the "Eversolar" protocol).

Technical Protocol Details (Eversolar):

Raw Socket Communication: The custom component must establish a raw asynchronous TCP connection (asyncio.open_connection) to the Waveshare converter, bypassing standard Modbus libraries like pymodbus.

Proprietary Frame Structure: The inverter expects specific hex-encoded request payloads and responds with proprietary hex frames.

Frame Header: All valid data frames in this protocol begin with a specific header, typically the hex bytes AA 55.

Checksums & Parsing: The component needs to implement custom logic to calculate/verify checksums and extract the relevant bytes (e.g., power in Watts, energy in kWh) based on the Eversolar protocol byte-mapping.

Requirements for the Custom Component:

Must be built using Home Assistant's modern DataUpdateCoordinator for polling.

Must handle raw TCP socket connections (handling timeouts, reconnects, and connection drops gracefully).

Needs to construct the proprietary polling hex string to request inverter data.

Needs to buffer the incoming TCP stream, look for the AA 55 header, validate the frame length and checksum, and decode the payload.

Expose the decoded values as Home Assistant SensorEntity objects with appropriate device_class (power, energy) and state_class (measurement, total_increasing).

Instructions for LLM:
Please generate the underlying Python code for this custom_component (including manifest.json, sensor.py, and the protocol/socket handling logic). Assume the protocol requires sending a specific register request and parsing an AA 55 response. Please structure the socket handling to be non-blocking using asyncio.