from flask import Flask, request, jsonify
import sqlite3
import datetime
import requests
import logging

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

# Function to connect to the database
def connect_db():
    conn = sqlite3.connect('plant_watering.db')
    return conn


# Initialize the database and create the table (run this once)
def init_db():
    conn = connect_db()
    cursor = conn.cursor()

    # Create the sensors table if it doesn't exist
    cursor.execute('''CREATE TABLE IF NOT EXISTS sensors (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        soil_moisture REAL,
                        temperature REAL,
                        humidity REAL,
                        timestamp TEXT
                     )''')
    conn.commit()
    conn.close()


# API endpoint to receive sensor data
@app.route('/api/sensor_data', methods=['POST'])
def receive_sensor_data():
    try:
        # Get data from the request
        sensor_data = request.json
        soil_moisture = sensor_data.get('soil_moisture')
        temperature = sensor_data.get('temperature')
        humidity = sensor_data.get('humidity')

        # Validate that all required fields are provided
        if soil_moisture is None or temperature is None or humidity is None:
            return jsonify({'error': 'Missing data'}), 400

        # Get the current timestamp
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Insert the data into the database
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sensors (soil_moisture, temperature, humidity, timestamp) VALUES (?, ?, ?, ?)",
                       (soil_moisture, temperature, humidity, timestamp))
        conn.commit()
        conn.close()

        return jsonify({'message': 'Data stored successfully'}), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/', methods=['GET'])
def home():
    return "<a href='/api/watering_decision'><h1>Get Watering Decision and The Water Amount in Litres</h1></a>"


# Function to get daily weather data from Open-Meteo API
def get_daily_weather_forecast(latitude, longitude):
    """
    Query the Open-Meteo API for daily weather forecast data.

    Parameters:
    - latitude (float): Latitude of the location.
    - longitude (float): Longitude of the location.

    Returns:
    - dict: A dictionary containing daily temperature and precipitation data.
    """
    url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&daily=temperature_2m_max,temperature_2m_min,precipitation_sum&timezone=auto"

    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an error for bad responses

        weather_data = response.json()
        daily_data = {
            'dates': weather_data['daily']['time'],
            'max_temperatures': weather_data['daily']['temperature_2m_max'],
            'min_temperatures': weather_data['daily']['temperature_2m_min'],
            'precipitation': weather_data['daily']['precipitation_sum']
        }
        print(daily_data)
        return daily_data

    except requests.exceptions.RequestException as e:
        print(f"Error fetching weather data: {e}")
        return None


# Function to analyze watering needs
def analyze_watering_need(daily_forecast, soil_moisture, humidity, watered_recently, current_humidity):
    # Define thresholds
    moisture_threshold = 30.0  # General soil moisture threshold
    critical_moisture_threshold = 10.0  # Critical moisture threshold
    humidity_threshold = 50.0  # Humidity threshold

    # Log input values
    logging.info(f"Soil Moisture: {soil_moisture}")

    # Step 1: Check soil moisture first
    if soil_moisture >= moisture_threshold:
        logging.info("Condition Met: Soil moisture is above the threshold, no watering needed.")
        return "No watering needed; soil moisture is sufficient."

    # Step 2: Only if soil moisture is low, proceed to check rain forecasts
    logging.info(f"Today's Precipitation: {daily_forecast['precipitation'][0]}")
    logging.info(f"Tomorrow's Precipitation: {daily_forecast['precipitation'][1]}")

    today_precipitation = daily_forecast['precipitation'][0]
    tomorrow_precipitation = daily_forecast['precipitation'][1]

    # Step 3: Check for rain today (no watering needed if rain expected today)
    if today_precipitation > 0:
        logging.info("Condition Met: Rain expected today, no watering needed despite low soil moisture.")
        return "No watering needed; rain is expected today."

    # Step 4: Check for rain tomorrow (but soil moisture critically low)
    if tomorrow_precipitation > 0:
        if soil_moisture < critical_moisture_threshold:
            logging.info("Condition Met: Rain expected tomorrow, but soil moisture critically low.")
            return "Minimal watering needed; soil moisture is critically low, but rain is expected tomorrow."
        logging.info("Condition Met: Rain expected tomorrow, soil moisture low but above critical threshold.")
        return "No watering needed; rain is expected tomorrow and soil moisture is not critically low."

    # Step 5: Check for low humidity or temperature increase, only if no rain is expected
    logging.info(f"Humidity: {humidity}")
    if humidity < humidity_threshold:
        logging.info("Condition Met: Low humidity, watering needed.")
        return "Watering needed; humidity is low and no rain is expected."

    logging.info(f"Today's Max Temperature: {daily_forecast['max_temperatures'][0]}")
    logging.info(f"Tomorrow's Max Temperature: {daily_forecast['max_temperatures'][1]}")

    if daily_forecast['max_temperatures'][1] > daily_forecast['max_temperatures'][0] + 2:
        logging.info("Condition Met: Significant temperature increase, watering needed.")
        return "Watering needed; temperature is expected to increase significantly."

    logging.info("Condition Met: No watering needed; conditions are stable despite low soil moisture.")
    return "No watering needed; conditions are stable."


# Function to calculate water amount if light rain is predicted
def calculate_water_amount(soil_moisture, area, soil_depth, predicted_rainfall):
    """
    Calculate the amount of water to apply based on soil moisture, area to water, soil depth, and predicted rainfall.

    Parameters:
    - soil_moisture (float): Current soil moisture level (as a percentage).
    - area (float): Area to be watered (in square meters).
    - soil_depth (float): Depth of the soil (in meters).
    - predicted_rainfall (float): Amount of rain expected (in mm).

    Returns:
    - float: Amount of water to apply (in liters).
    """
    moisture_threshold = 20.0  # Adjusted desired moisture level in mm (example value)
    soil_depth_mm = soil_depth * 1000  # Convert depth to mm

    # Current moisture in mm
    current_moisture_mm = (soil_moisture / 100) * soil_depth_mm
    desired_moisture_mm = moisture_threshold * area  # Total moisture desired for the area

    # Calculate the water deficit taking rainfall into account
    water_deficit_mm = desired_moisture_mm - current_moisture_mm - (predicted_rainfall * area)

    # Log values for debugging
    logging.debug(f"Current Moisture: {current_moisture_mm} mm")
    logging.debug(f"Desired Moisture: {desired_moisture_mm} mm")
    logging.debug(f"Predicted Rainfall: {predicted_rainfall} mm")
    logging.debug(f"Water Deficit: {water_deficit_mm} mm")

    # Convert to liters; ensure non-negative
    water_deficit_liters = max(0, water_deficit_mm) * area / 1000  # Convert mm to liters

    return water_deficit_liters


# API endpoint to analyze watering needs
@app.route('/api/watering_decision', methods=['GET'])
def watering_decision():
    # Get the last recorded sensor data
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT soil_moisture, temperature, humidity FROM sensors ORDER BY timestamp DESC LIMIT 1")
    sensor_data = cursor.fetchone()
    conn.close()

    if sensor_data is None:
        return jsonify({'error': 'No sensor data available'}), 404

    soil_moisture, temperature, humidity = sensor_data

    latitude = 11.6538
    longitude = 78.1554

    daily_forecast = get_daily_weather_forecast(latitude, longitude)
    if daily_forecast:
        watered_recently = False  # This should be a real flag from your watering logic
        current_humidity = humidity  # Assuming current humidity is taken from the sensor data
        decision = analyze_watering_need(daily_forecast, soil_moisture, humidity, watered_recently, current_humidity)

        # Calculate water amount if light rain is predicted
        predicted_rainfall = daily_forecast['precipitation'][1]  # Assuming tomorrow's rainfall is of interest
        area = 2000.67  # Example area to be watered in square meters
        soil_depth = 0.30  # Example soil depth in meters
        water_amount = calculate_water_amount(soil_moisture, area, soil_depth, predicted_rainfall)
        if "No watering needed" in decision:
            # If no watering is needed, we can set water amount to 0
            water_amount = 0  # Optional: Can also be handled in calculate_water_amount function


        return jsonify({
            'watering_decision': decision,
            'water_amount_liters': water_amount
        }), 200
    else:
        return jsonify({'error': 'Error fetching weather data'}), 500


# Run the app
if __name__ == '__main__':
    # init_db()  # Initialize the database if it hasn't been created
    app.run(host='0.0.0.0', port=5000)
