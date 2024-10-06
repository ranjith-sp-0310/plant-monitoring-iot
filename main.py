from flask import Flask, request, jsonify
import sqlite3
import datetime
import requests
import logging

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

soil_moisture_threshold_percentage = 0


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
        # print(daily_data)
        return daily_data

    except requests.exceptions.RequestException as e:
        print(f"Error fetching weather data: {e}")
        return None


def get_et0_from_openmeteo(latitude, longitude):
    """
    Fetch the ET₀ (reference evapotranspiration) from Open-Meteo API for a given location.

    Parameters:
    - latitude (float): Latitude of the location.
    - longitude (float): Longitude of the location.

    Returns:
    - float: The latest ET₀ value in mm/day.
    """
    url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&hourly=et0_fao_evapotranspiration&timezone=auto"

    try:
        response = requests.get(url)
        data = response.json()
        # Get the latest ET₀ value from the hourly forecast
        et0_values = data['hourly']['et0_fao_evapotranspiration']
        et0 = et0_values[0]  # Assuming we take the first (latest) value
        if et0 <= 0:
            et0 = 0.45  # may cause overwatering, Use Historical values to average

        logging.debug(f"Fetched ET₀ from Open-Meteo: {et0} mm/day")

        return et0

    except Exception as e:
        logging.error(f"Failed to fetch ET₀: {e}")
        return None


def convert_moisture_to_percentage(moisture_threshold_mm, soil_depth_m, field_capacity=0.3):
    # Calculate the moisture percentage
    moisture_percentage = (moisture_threshold_mm / (soil_depth_m * field_capacity)) * 100
    conn = connect_db()
    cursor = conn.cursor()
    threshold = float(moisture_percentage)  # Ensure this is a float

    # The correct way to pass it to the query
    cursor.execute("INSERT INTO moisture_thresholds (threshold) VALUES (?)", (threshold,))
    conn.commit()
    conn.close()

    return moisture_percentage


def calculate_etc(et0, kc=1.0):
    print(et0)
    etc = kc * et0
    return etc * 100


# Function to calculate water amount if light rain is predicted
def calculate_water_amount(soil_moisture, area, soil_depth, predicted_rainfall, latitude, longitude):
    """
    Calculate the amount of water to apply based on soil moisture, area to water, soil depth,
    predicted rainfall, and ET₀ fetched from Open-Meteo API.

    Parameters:
    - soil_moisture (float): Current soil moisture level (as a percentage).
    - area (float): Area to be watered (in square meters).
    - soil_depth (float): Depth of the soil (in meters).
    - predicted_rainfall (float): Amount of rain expected (in mm).
    - latitude (float): Latitude of the location (for ET₀ request).
    - longitude (float): Longitude of the location (for ET₀ request).
    - kc (float): Crop coefficient for potatoes (adjusted based on growth stage).

    Returns:
    - float: Amount of water to apply (in liters).
    """
    # Fetch the ET₀ value from Open-Meteo API
    et0 = get_et0_from_openmeteo(latitude, longitude)
    if et0 is None:
        logging.error("Failed to fetch ET₀, cannot calculate water amount.")
        return None

    # Crop water requirement calculation (ETc = ET₀ * Kc)
    etc = calculate_etc(et0)  # Crop evapotranspiration (total water needed in mm)

    # Adjusted desired moisture level for potatoes
    moisture_threshold = etc  # in mm
    print(moisture_threshold)
    # Use ETc as the desired water level (mm)
    soil_depth_mm = soil_depth * 1000  # Convert soil depth to mm
    print("soil depth in mm " + str(soil_depth_mm))
    moisture_percentage = convert_moisture_to_percentage(moisture_threshold, soil_depth_mm)
    print("moisture threshold is " + str(moisture_percentage))
    # Current moisture in mm
    current_moisture_mm = (soil_moisture / 100) * soil_depth_mm

    # Calculate total desired water based on area and crop water requirement (ETc)
    desired_moisture_mm = moisture_threshold * area  # Total moisture required for the area

    # Calculate water deficit, adjusting for predicted rainfall
    water_deficit_mm = desired_moisture_mm - current_moisture_mm - (predicted_rainfall * area)

    # Log values for debugging purposes
    logging.debug(f"ET₀: {et0} mm/day")
    #    logging.debug(f"ETc (Water Need for Potatoes): {etc} mm/day")
    logging.debug(f"Current Moisture: {current_moisture_mm} mm")
    logging.debug(f"Desired Moisture (Potato): {desired_moisture_mm} mm")
    logging.debug(f"Predicted Rainfall: {predicted_rainfall} mm")
    logging.debug(f"Water Deficit: {water_deficit_mm} mm")

    # Convert water deficit to liters and ensure it's non-negative
    water_deficit_liters = max(0, water_deficit_mm) * area / 1000  # Convert mm to liters

    return water_deficit_liters


# Function to analyze watering needs
def analyze_watering_need(daily_forecast, soil_moisture, humidity, watered_recently):
    #Everything in percentage
    moisture_threshold = soil_moisture_threshold_percentage
    print("Global Moisture Threshold:" + str(moisture_threshold))
    critical_moisture_threshold = soil_moisture_threshold_percentage / 3  # Critical moisture threshold
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
    if today_precipitation > 0.5:
        logging.info("Condition Met: Rain expected today, no watering needed despite low soil moisture.")
        return "No watering needed; rain is expected today."

    # Step 4: Check for rain tomorrow (but soil moisture critically low)
    if tomorrow_precipitation > 0.5:
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

    # latitude = 11.6538 #salem
    # longitude = 78.1554 #salem
    latitude = 16.2997 #Guntur -Andhra
    longitude = 80.4573 #Guntur - Andhra

    area = 100  # Example area to be watered in square meters
    soil_depth = 0.3  # Example soil depth in meters

    et0 = get_et0_from_openmeteo(latitude, longitude)
    soil_moisture_threshold = calculate_etc(et0)
    global soil_moisture_threshold_percentage
    soil_moisture_threshold_percentage = convert_moisture_to_percentage(soil_moisture_threshold, soil_depth * 1000)

    daily_forecast = get_daily_weather_forecast(latitude, longitude)
    if daily_forecast:
        watered_recently = False  # This should be a real flag from your watering logic
        decision = analyze_watering_need(daily_forecast, soil_moisture, humidity, watered_recently)

        # Calculate water amount if light rain is predicted
        predicted_rainfall = daily_forecast['precipitation'][1]  # Assuming tomorrow's rainfall is of interest

        water_amount = calculate_water_amount(soil_moisture, area, soil_depth, predicted_rainfall, latitude, longitude)
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

# Need to check Edge Cases for Extremely low non-zero et0 values