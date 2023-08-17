# LoRa Text Messaging based on CDS

This project focuses on enabling communication for users without cellular or internet connections, using LoRa devices in conjunction with mobile devices such as smartphones and laptops. The code is written in MicroPython and designed for Pycom LoPy4 devices.

## Project Overview

In scenarios where conventional communication infrastructure is unavailable, this project aims to provide a solution for users to communicate using LoRa technology. LoRa (Long Range) is a low-power wireless communication protocol that allows long-range communication even in areas with limited connectivity.

The primary objective of this project is to create a system where LoRa devices automatically establish a backbone network by identifying and forming a connected dominating set (CDS) within the network. This backbone network serves as the foundation for disseminating user messages, enabling communication in situations where traditional communication methods are unavailable.

## Features

- Utilizes LoRa devices (Pycom LoPy4) and mobile devices (smartphones, laptops) for communication.
- Automatically establishes a backbone network by identifying a connected dominating set within the network.
- Adapts dynamically to network changes, accommodating device disconnections and new device additions.
- Offers a user interface through a microcontroller-hosted webpage for sending and receiving messages.

## Getting Started

To begin using the "LoRa Text Messaging based on CDS" system, follow these steps:

1. Set up your Pycom LoPy4 devices with the provided MicroPython code.
2. Deploy the devices in your intended communication area.
3. Upon device activation, the system will automatically establish a backbone network using CDS.
4. Access the microcontroller-hosted webpage by connecting to the generated WiFi access point to send and receive messages within the established network.

## License

This project is licensed under the [MIT License](LICENSE), which means you're free to use, modify, and distribute the code according to the terms of the license.

