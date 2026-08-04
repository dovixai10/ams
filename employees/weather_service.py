"""
Weather Service Module
Handles weather data fetching and caching
"""

import requests
import logging
from django.core.cache import cache
from django.conf import settings
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Default location (can be configured in settings)
DEFAULT_LOCATION = {
    'city': 'Bangalore',
    'lat': 12.9716,
    'lon': 77.5946,
    'country': 'IN'
}

# Weather API configuration
WEATHER_API_KEY = getattr(settings, 'WEATHER_API_KEY', None)
WEATHER_API_URL = 'https://api.openweathermap.org/data/2.5/weather'
WEATHER_CACHE_TIMEOUT = 1800  # 30 minutes


class WeatherService:
    """Service for fetching and managing weather data"""
    
    @staticmethod
    def get_weather(lat=None, lon=None, city=None):
        """
        Fetch weather data for a location
        
        Args:
            lat (float): Latitude
            lon (float): Longitude
            city (str): City name
            
        Returns:
            dict: Weather data or None
        """
        if not WEATHER_API_KEY:
            logger.warning('Weather API key not configured')
            return WeatherService._get_default_weather()
        
        # Use default location if not provided
        if not (lat and lon) and not city:
            lat = DEFAULT_LOCATION['lat']
            lon = DEFAULT_LOCATION['lon']
        
        # Create cache key
        cache_key = f'weather_{lat}_{lon}_{city}'
        
        # Check cache first
        cached_weather = cache.get(cache_key)
        if cached_weather:
            return cached_weather
        
        try:
            # Prepare request parameters
            params = {
                'appid': WEATHER_API_KEY,
                'units': 'metric'  # Celsius
            }
            
            if lat and lon:
                params['lat'] = lat
                params['lon'] = lon
            elif city:
                params['q'] = city
            
            # Make API request
            response = requests.get(WEATHER_API_URL, params=params, timeout=5)
            response.raise_for_status()
            
            data = response.json()
            
            # Parse weather data
            weather = WeatherService._parse_weather_data(data)
            
            # Cache the result
            cache.set(cache_key, weather, WEATHER_CACHE_TIMEOUT)
            
            return weather
            
        except requests.exceptions.RequestException as e:
            logger.error(f'Weather API error: {str(e)}')
            return WeatherService._get_default_weather()
        except Exception as e:
            logger.error(f'Error processing weather data: {str(e)}')
            return WeatherService._get_default_weather()
    
    @staticmethod
    def _parse_weather_data(data):
        """Parse OpenWeatherMap API response"""
        try:
            main = data.get('main', {})
            weather = data.get('weather', [{}])[0]
            wind = data.get('wind', {})
            
            return {
                'success': True,
                'city': data.get('name', 'Unknown'),
                'country': data.get('sys', {}).get('country', ''),
                'temperature': round(main.get('temp', 0)),
                'feels_like': round(main.get('feels_like', 0)),
                'humidity': main.get('humidity', 0),
                'pressure': main.get('pressure', 0),
                'condition': weather.get('main', 'Unknown'),
                'description': weather.get('description', '').title(),
                'icon': weather.get('icon', '01d'),
                'wind_speed': round(wind.get('speed', 0), 1),
                'wind_deg': wind.get('deg', 0),
                'cloudiness': data.get('clouds', {}).get('all', 0),
                'visibility': data.get('visibility', 0),
                'sunrise': data.get('sys', {}).get('sunrise', 0),
                'sunset': data.get('sys', {}).get('sunset', 0),
                'timestamp': datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f'Error parsing weather data: {str(e)}')
            return WeatherService._get_default_weather()
    
    @staticmethod
    def _get_default_weather():
        """Return default weather data when API fails"""
        return {
            'success': False,
            'city': DEFAULT_LOCATION['city'],
            'country': DEFAULT_LOCATION['country'],
            'temperature': 25,
            'feels_like': 25,
            'humidity': 60,
            'pressure': 1013,
            'condition': 'Partly Cloudy',
            'description': 'Partly Cloudy',
            'icon': '02d',
            'wind_speed': 5.0,
            'wind_deg': 180,
            'cloudiness': 50,
            'visibility': 10000,
            'sunrise': 0,
            'sunset': 0,
            'timestamp': datetime.now().isoformat(),
        }
    
    @staticmethod
    def get_weather_icon(icon_code):
        """
        Convert OpenWeatherMap icon code to emoji
        
        Args:
            icon_code (str): Icon code from API (e.g., '01d', '02n')
            
        Returns:
            str: Emoji representation
        """
        icon_map = {
            '01d': '☀️',   # Clear sky day
            '01n': '🌙',   # Clear sky night
            '02d': '⛅',   # Few clouds day
            '02n': '☁️',   # Few clouds night
            '03d': '☁️',   # Scattered clouds day
            '03n': '☁️',   # Scattered clouds night
            '04d': '☁️',   # Broken clouds day
            '04n': '☁️',   # Broken clouds night
            '09d': '🌧️',   # Shower rain day
            '09n': '🌧️',   # Shower rain night
            '10d': '🌦️',   # Rain day
            '10n': '🌧️',   # Rain night
            '11d': '⛈️',   # Thunderstorm day
            '11n': '⛈️',   # Thunderstorm night
            '13d': '❄️',   # Snow day
            '13n': '❄️',   # Snow night
            '50d': '🌫️',   # Mist day
            '50n': '🌫️',   # Mist night
        }
        return icon_map.get(icon_code, '🌤️')
    
    @staticmethod
    def get_weather_theme(condition, temperature):
        """
        Determine UI theme based on weather
        
        Args:
            condition (str): Weather condition
            temperature (int): Temperature in Celsius
            
        Returns:
            dict: Theme configuration
        """
        condition = condition.lower()
        
        # Rainy weather
        if 'rain' in condition or 'drizzle' in condition:
            return {
                'name': 'rainy',
                'gradient': 'linear-gradient(135deg, #4a5568 0%, #2d3748 100%)',
                'text_color': '#ffffff',
                'accent': '#60a5fa',
                'icon': '🌧️'
            }
        
        # Thunderstorm
        if 'thunder' in condition or 'storm' in condition:
            return {
                'name': 'storm',
                'gradient': 'linear-gradient(135deg, #1a202c 0%, #2d3748 100%)',
                'text_color': '#ffffff',
                'accent': '#fbbf24',
                'icon': '⛈️'
            }
        
        # Snow/Cold
        if 'snow' in condition or temperature < 5:
            return {
                'name': 'cold',
                'gradient': 'linear-gradient(135deg, #e0f2fe 0%, #bae6fd 100%)',
                'text_color': '#0c4a6e',
                'accent': '#06b6d4',
                'icon': '❄️'
            }
        
        # Clear/Sunny
        if 'clear' in condition or 'sunny' in condition:
            return {
                'name': 'sunny',
                'gradient': 'linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%)',
                'text_color': '#ffffff',
                'accent': '#dc2626',
                'icon': '☀️'
            }
        
        # Cloudy
        if 'cloud' in condition or 'overcast' in condition:
            return {
                'name': 'cloudy',
                'gradient': 'linear-gradient(135deg, #d1d5db 0%, #9ca3af 100%)',
                'text_color': '#1f2937',
                'accent': '#6366f1',
                'icon': '☁️'
            }
        
        # Hot weather
        if temperature > 30:
            return {
                'name': 'hot',
                'gradient': 'linear-gradient(135deg, #fca5a5 0%, #f87171 100%)',
                'text_color': '#ffffff',
                'accent': '#dc2626',
                'icon': '🔥'
            }
        
        # Default
        return {
            'name': 'default',
            'gradient': 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
            'text_color': '#ffffff',
            'accent': '#fbbf24',
            'icon': '🌤️'
        }
    
    @staticmethod
    def get_weather_recommendation(condition, temperature):
        """
        Get activity recommendations based on weather
        
        Args:
            condition (str): Weather condition
            temperature (int): Temperature in Celsius
            
        Returns:
            str: Recommendation message
        """
        condition = condition.lower()
        
        if 'rain' in condition or 'drizzle' in condition:
            return '☔ Rainy day - Carry an umbrella'
        
        if 'thunder' in condition or 'storm' in condition:
            return '⛈️ Thunderstorm - Stay indoors'
        
        if 'snow' in condition:
            return '❄️ Snowy - Wear warm clothes'
        
        if temperature > 35:
            return '🔥 Very hot - Stay hydrated'
        
        if temperature < 5:
            return '❄️ Very cold - Wear warm clothes'
        
        if 'clear' in condition or 'sunny' in condition:
            return '☀️ Beautiful day - Perfect for outdoor work'
        
        return '🌤️ Pleasant weather'
