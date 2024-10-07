```
# Plant Watering System

## Overview

The Plant Watering System is an automated solution designed to optimize plant care by monitoring environmental conditions and using external weather data. This system utilizes soil moisture, temperature, and humidity sensors to determine when to water plants, ensuring they receive the right amount of water based on their needs.

## Features

- **Real-time Data Collection**: Collects data from soil moisture, temperature, and humidity sensors.
- **Weather Forecasting**: Integrates with the OpenMeteo API to retrieve rain predictions.
- **Automated Watering**: Calculates water requirements based on sensor data and plant type.
- **Feedback Mechanism**: Assesses the accuracy of weather predictions to improve future decisions.
- **SQLite Database**: Stores sensor data for historical analysis and monitoring.

## Requirements

### Hardware

- ESP32 microcontroller
- Soil moisture sensor
- Temperature and humidity sensor
- Watering mechanism (e.g., a pump)

### Software

- Python 3.x
- SQLite
- `requests` library (for API calls)
- Any necessary libraries for interfacing with the ESP32 (e.g., `MicroPython` or `Arduino` libraries)

## Setup

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/yourusername/plant-watering-system.git
   cd plant-watering-system
   ```

2. **Create a Virtual Environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```

3. **Install Dependencies**:
   ```bash
   pip install requests
   ```

4. **Configure Your API Key**:
   - Obtain an API key from OpenMeteo and update it in the code where specified.

5. **Connect the Sensors**:
   - Set up the sensors with the ESP32 as per your wiring diagram.

## Usage

Run the main script to start the system:

```bash
python main.py
```

The program will continuously monitor sensor data and weather conditions, automatically watering the plants as needed.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please fork the repository and submit a pull request for any improvements or new features.

## Acknowledgments

- [OpenMeteo](https://OpenMeteomap.org/) for providing weather data.
- [SQLite](https://www.sqlite.org/) for easy database management.
```
