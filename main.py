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

        return daily_data

    except requests.exceptions.RequestException as e:
        print(f"Error fetching weather data: {e}")
        return None


# Function to analyze watering needs
def analyze_watering_need(daily_forecast, soil_moisture, humidity, watered_recently, current_humidity):
    """
    Analyze whether watering is needed based on today's and tomorrow's weather data,
    soil moisture, and humidity.
    """

    # Extract relevant forecast data
    today_index = 0
    tomorrow_index = 1
    today_precipitation = daily_forecast['precipitation'][today_index]
    tomorrow_precipitation = daily_forecast['precipitation'][tomorrow_index]
    today_max_temp = daily_forecast['max_temperatures'][today_index]
    tomorrow_max_temp = daily_forecast['max_temperatures'][tomorrow_index]

    # Define thresholds
    moisture_threshold = 30.0  # Soil moisture threshold
    humidity_threshold = 50.0  # Humidity threshold

    # Log all input values for debugging
    logging.info(f"Today's Precipitation: {today_precipitation}")
    logging.info(f"Tomorrow's Precipitation: {tomorrow_precipitation}")
    logging.info(f"Soil Moisture: {soil_moisture}")
    logging.info(f"Humidity: {humidity}")
    logging.info(f"Current Max Temperature: {today_max_temp}")
    logging.info(f"Tomorrow's Max Temperature: {tomorrow_max_temp}")
    logging.info(f"Watered Recently: {watered_recently}")
    logging.info(f"Current Humidity: {current_humidity}")

    # Check for immediate rain today
    if today_precipitation > 0:
        logging.info("Condition Met: Rain expected today.")
        return "No watering needed; rain is expected today."

    # If no rain today but rain expected tomorrow
    if today_precipitation == 0 and tomorrow_precipitation > 0:
        if soil_moisture < moisture_threshold:
            logging.info("Condition Met: No rain today but rain expected tomorrow, soil moisture is low.")
            return "Watering not needed; soil moisture is low, but rain is expected tomorrow."
        else:
            logging.info("Condition Met: No rain today but rain expected tomorrow, soil moisture is adequate.")
            return "No watering needed; soil moisture is adequate despite low moisture."

    # Check if soil moisture is below the threshold
    if soil_moisture < moisture_threshold:
        logging.info("Condition Met: Soil moisture is below the threshold.")
        return "Watering needed; soil moisture is below the threshold."

    # Check humidity level
    if humidity < humidity_threshold:
        logging.info("Condition Met: Humidity is below the threshold.")
        return "Watering needed; humidity is below the threshold."

    # Check for significant temperature increase
    if tomorrow_max_temp > today_max_temp + 2:  # Significant temperature increase
        logging.info("Condition Met: Tomorrow's temperature is significantly higher.")
        return "Watering needed; temperature is significantly higher tomorrow."

    # Check for significant temperature drop
    if tomorrow_max_temp < today_max_temp:
        logging.info("Condition Met: Tomorrow's temperature is cooler, evaporation reduced.")
        return "No watering needed; cooler temperatures will reduce evaporation."

    # Check for overwatering risk
    if watered_recently and current_humidity > humidity_threshold:
        logging.info("Condition Met: Recently watered and high humidity, no watering needed.")
        return "No watering needed; soil has been watered recently and humidity is high."

    logging.info("Condition Met: No watering needed, conditions are stable.")
    return "No watering needed; conditions are stable."


# Function to calculate water amount if light rain is predicted
def calculate_water_amount(soil_moisture, area, soil_depth, predicted_rainfall):
    """
    Calculate the amount of water to apply based on soil moisture, area to water, soil depth, and predicted rainfall.

    Parameters:
    - soil_moisture (float): Current soil moisture level.
    - area (float): Area to be watered (in square meters).
    - soil_depth (float): Depth of the soil (in meters).
    - predicted_rainfall (float): Amount of rain expected (in mm).

    Returns:
    - float: Amount of water to apply (in liters).
    """
    moisture_threshold = 60.0  # Desired moisture level in mm
    soil_depth_mm = soil_depth * 1000  # Convert depth to mm

    current_moisture_mm = soil_moisture / 100 * soil_depth_mm
    desired_moisture_mm = moisture_threshold * area  # Total moisture desired for the area

    water_deficit_mm = desired_moisture_mm - current_moisture_mm + predicted_rainfall * area
    water_deficit_liters = max(0, water_deficit_mm) * area / 1000  # Convert to liters

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

    latitude = 26.9176
    longitude = 70.9039

    daily_forecast = get_daily_weather_forecast(latitude, longitude)
    if daily_forecast:
        watered_recently = False  # This should be a real flag from your watering logic
        current_humidity = humidity  # Assuming current humidity is taken from the sensor data
        decision = analyze_watering_need(daily_forecast, soil_moisture, humidity, watered_recently, current_humidity)

        # Calculate water amount if light rain is predicted
        predicted_rainfall = daily_forecast['precipitation'][1]  # Assuming tomorrow's rainfall is of interest
        area = 20.0  # Example area to be watered in square meters
        soil_depth = 0.15  # Example soil depth in meters
        water_amount = calculate_water_amount(soil_moisture, area, soil_depth, predicted_rainfall)

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
