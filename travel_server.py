import os
import json
import uuid
import requests
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable

from amadeus import Client, ResponseError
from mcp.server.fastmcp import FastMCP, Context

# =====================================================================
# APPLICATION CONTEXT AND LIFECYCLE
# =====================================================================

@dataclass
class AppContext:
    amadeus_client: Client

@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage Amadeus client lifecycle"""
    api_key = os.environ.get("AMADEUS_API_KEY")
    api_secret = os.environ.get("AMADEUS_API_SECRET")

    if not api_key or not api_secret:
        raise ValueError("AMADEUS_API_KEY and AMADEUS_API_SECRET must be set as environment variables")

    amadeus_client = Client(
        client_id=api_key,
        client_secret=api_secret
    )

    try:
        yield AppContext(amadeus_client=amadeus_client)
    finally:
        pass

# Initialize FastMCP server with lifespan
mcp = FastMCP("Travel Concierge", dependencies=["amadeus", "requests", "geopy"], lifespan=app_lifespan)

# =====================================================================
# UTILITY FUNCTIONS
# =====================================================================

def get_serpapi_key() -> str:
    """Get SerpAPI key from environment variable."""
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        raise ValueError("SERPAPI_KEY environment variable is required")
    return api_key

def get_exchange_rate_api_key() -> str:
    """Get ExchangeRate-API key from environment variable."""
    api_key = os.getenv("EXCHANGE_RATE_API_KEY")
    if not api_key:
        raise ValueError("EXCHANGE_RATE_API_KEY environment variable is required")
    return api_key

def get_geolocator():
    """Initialize and return a geolocator with rate limiting."""
    email_identifier = f"{uuid.uuid4()}.com"
    geolocator = Nominatim(user_agent=email_identifier)
    return RateLimiter(geolocator.geocode, min_delay_seconds=1), RateLimiter(geolocator.reverse, min_delay_seconds=1)

def get_nws_headers() -> Dict[str, str]:
    """Get headers for NWS API requests with required User-Agent."""
    return {
        "User-Agent": "CombinedTravelMCP/1.0 (combined-travel-mcp, support@example.com)",
        "Accept": "application/geo+json"
    }

def make_nws_request(endpoint: str) -> Optional[Dict[str, Any]]:
    """Make a request to the NWS API with proper error handling."""
    try:
        response = requests.get(endpoint, headers=get_nws_headers(), timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error making request to {endpoint}: {str(e)}")
        return None

# =====================================================================
# COMBINED FLIGHT SEARCH TOOLS
# =====================================================================

@mcp.tool()
def search_flights_serpapi(
    departure_id: str,
    arrival_id: str,
    outbound_date: str,
    return_date: Optional[str] = None,
    trip_type: int = 1,
    adults: int = 1,
    children: int = 0,
    infants_in_seat: int = 0,
    infants_on_lap: int = 0,
    travel_class: int = 1,
    currency: str = "USD",
    country: str = "us",
    language: str = "en",
    max_results: int = 10
) -> Dict[str, Any]:
    """
    🛫 Find the perfect flights using Google Flights! Your AI travel concierge searches through thousands of flight options to find the best deals and most convenient routes for your journey.
    
    This tool uses Google's comprehensive flight database to provide real-time pricing, schedule information, and booking options from airlines worldwide.
    
    Args:
        departure_id: Where you're flying from - airport code (e.g., 'DEL', 'LKO') or city name
        arrival_id: Your dream destination - airport code (e.g., 'CDG', 'LHR') or city name  
        outbound_date: When you want to depart (YYYY-MM-DD format, e.g., '2025-06-15')
        return_date: When you want to return (YYYY-MM-DD format) - leave empty for one-way trips
        trip_type: Type of journey (1=Round trip, 2=One way, 3=Multi-city adventure)
        adults: Number of adult travelers (18+)
        children: Number of children (2-11 years old)
        infants_in_seat: Number of infants with their own seat (under 2)
        infants_on_lap: Number of lap infants (under 2)
        travel_class: Your preferred comfort level (1=Economy, 2=Premium Economy, 3=Business, 4=First Class)
        currency: Your preferred currency for pricing (default: USD)
        country: Your country for localized results
        language: Your preferred language
        max_results: Maximum number of flight options to show you
        
    Returns:
        Curated flight options with prices, schedules, and booking details tailored to your travel needs
    """
    
    try:
        api_key = get_serpapi_key()
        
        # Build search parameters
        params = {
            "engine": "google_flights",
            "departure_id": departure_id,
            "arrival_id": arrival_id,
            "outbound_date": outbound_date,
            "type": trip_type,
            "adults": adults,
            "children": children,
            "infants_in_seat": infants_in_seat,
            "infants_on_lap": infants_on_lap,
            "travel_class": travel_class,
            "currency": currency,
            "hl": language,
            "gl": country,
            "api_key": api_key
        }
        
        if return_date and trip_type == 1:  # Round trip
            params["return_date"] = return_date
        
        # Make API request
        response = requests.get("https://serpapi.com/search", params=params)
        response.raise_for_status()
        
        flight_data = response.json()
        
        # Process flight results
        processed_results = {
            "provider": "Google Flights (SerpAPI)",
            "search_metadata": {
                "departure": departure_id,
                "arrival": arrival_id,
                "outbound_date": outbound_date,
                "return_date": return_date,
                "trip_type": "Round trip" if trip_type == 1 else "One way" if trip_type == 2 else "Multi-city",
                "passengers": {
                    "adults": adults,
                    "children": children,
                    "infants_in_seat": infants_in_seat,
                    "infants_on_lap": infants_on_lap
                },
                "travel_class": ["Economy", "Premium economy", "Business", "First"][travel_class - 1],
                "currency": currency,
                "search_timestamp": datetime.now().isoformat()
            },
            "best_flights": flight_data.get("best_flights", [])[:max_results],
            "other_flights": flight_data.get("other_flights", [])[:max_results],
            "price_insights": flight_data.get("price_insights", {}),
            "airports": flight_data.get("airports", [])
        }
        
        return processed_results
        
    except requests.exceptions.RequestException as e:
        return {"error": f"Google Flights API request failed: {str(e)}"}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}

@mcp.tool()
def search_flights_amadeus(
    originLocationCode: str,
    destinationLocationCode: str,
    departureDate: str,
    adults: int,
    ctx: Context,
    returnDate: str = None,
    children: int = None,
    infants: int = None,
    travelClass: str = None,
    includedAirlineCodes: str = None,
    excludedAirlineCodes: str = None,
    nonStop: bool = None,
    currencyCode: str = None,
    maxPrice: int = None,
    max: int = 250
) -> str:
    """
    🛫 Find professional flight offers using Amadeus Global Distribution System! Access real-time airline inventory with detailed fare information and booking classes.

    This tool provides access to the same flight data used by travel professionals, with comprehensive airline partnerships and detailed fare breakdown information.

    Args:
        originLocationCode: IATA code of the departure city/airport (e.g., SYD for Sydney)
        destinationLocationCode: IATA code of the destination city/airport (e.g., BKK for Bangkok)
        departureDate: Departure date in ISO 8601 format (YYYY-MM-DD, e.g., 2023-05-02)
        adults: Number of adult travelers (age 12+), must be 1-9
        returnDate: Return date in ISO 8601 format (YYYY-MM-DD), if round-trip is desired
        children: Number of child travelers (age 2-11)
        infants: Number of infant travelers (age <= 2)
        travelClass: Travel class (ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST)
        includedAirlineCodes: Comma-separated IATA airline codes to include (e.g., '6X,7X')
        excludedAirlineCodes: Comma-separated IATA airline codes to exclude (e.g., '6X,7X')
        nonStop: If true, only non-stop flights are returned
        currencyCode: ISO 4217 currency code (e.g., EUR for Euro)
        maxPrice: Maximum price per traveler, positive integer with no decimals
        max: Maximum number of flight offers to return
    """
    if adults and not (1 <= adults <= 9):
        return json.dumps({"error": "Adults must be between 1 and 9"})

    if children and infants and adults and (adults + children > 9):
        return json.dumps({"error": "Total number of seated travelers (adults + children) cannot exceed 9"})

    if infants and adults and (infants > adults):
        return json.dumps({"error": "Number of infants cannot exceed number of adults"})

    amadeus_client = ctx.request_context.lifespan_context.amadeus_client
    params = {}
    params["originLocationCode"] = originLocationCode
    params["destinationLocationCode"] = destinationLocationCode
    params["departureDate"] = departureDate
    params["adults"] = adults

    if returnDate:
        params["returnDate"] = returnDate
    if children is not None:
        params["children"] = children
    if infants is not None:
        params["infants"] = infants
    if travelClass:
        params["travelClass"] = travelClass
    if includedAirlineCodes:
        params["includedAirlineCodes"] = includedAirlineCodes
    if excludedAirlineCodes:
        params["excludedAirlineCodes"] = excludedAirlineCodes
    if nonStop is not None:
        params["nonStop"] = nonStop
    if currencyCode:
        params["currencyCode"] = currencyCode
    if maxPrice is not None:
        params["maxPrice"] = maxPrice
    if max is not None:
        params["max"] = max

    try:
        ctx.info(f"Searching Amadeus flights from {originLocationCode} to {destinationLocationCode}")
        ctx.info(f"API parameters: {json.dumps(params)}")

        response = amadeus_client.shopping.flight_offers_search.get(**params)
        result = response.body
        result["provider"] = "Amadeus GDS"
        result["search_timestamp"] = datetime.now().isoformat()
        return json.dumps(result)
    except ResponseError as error:
        error_msg = f"Amadeus API error: {str(error)}"
        ctx.info(f"Error: {error_msg}")
        return json.dumps({"error": error_msg})
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        ctx.info(f"Error: {error_msg}")
        return json.dumps({"error": error_msg})

# =====================================================================
# COMBINED HOTEL SEARCH TOOLS
# =====================================================================

@mcp.tool()
def search_hotels_serpapi(
    location: str,
    check_in_date: str,
    check_out_date: str,
    adults: int = 2,
    children: int = 0,
    children_ages: Optional[List[int]] = None,
    currency: str = "USD",
    country: str = "us",
    language: str = "en",
    sort_by: Optional[int] = None,
    hotel_class: Optional[List[int]] = None,
    amenities: Optional[List[int]] = None,
    property_types: Optional[List[int]] = None,
    brands: Optional[List[int]] = None,
    free_cancellation: bool = False,
    special_offers: bool = False,
    vacation_rentals: bool = False,
    bedrooms: Optional[int] = None,
    max_results: int = 20
) -> Dict[str, Any]:
    """
    🏨 Discover your perfect accommodation using Google Hotels! Your AI travel concierge will find the ideal lodging that matches your style, budget, and dreams for the perfect stay.
    
    This tool searches through Google's comprehensive hotel database, including major chains, boutique properties, and vacation rentals worldwide.
    
    Args:
        location: Your destination (e.g., 'Paris city center', 'Bali beachfront', 'Tokyo Shibuya')
        check_in_date: When you'd like to arrive (YYYY-MM-DD format, e.g., '2025-06-15')
        check_out_date: When you're planning to leave (YYYY-MM-DD format, e.g., '2025-06-20')
        adults: Number of adult guests sharing the space
        children: Number of children (if traveling with family)
        children_ages: Ages of children for appropriate room configurations
        currency: Your preferred currency for pricing (default: USD)
        country: Your country for localized results and offers
        language: Your preferred language
        sort_by: How you'd like results sorted (3=Best deals, 8=Highest rated, 13=Most popular)
        hotel_class: Star rating preference (e.g., [4, 5] for luxury properties)
        amenities: Must-have amenities for your perfect stay
        property_types: Type of accommodation you prefer
        brands: Favorite hotel brands or chains
        free_cancellation: True if you need booking flexibility
        special_offers: True to see exclusive deals and packages
        vacation_rentals: True to search apartments, villas, and unique stays
        bedrooms: Minimum bedrooms needed (for vacation rentals)
        max_results: Maximum number of options to show you
        
    Returns:
        Curated accommodation options with detailed information, pricing, and booking details
    """
    
    try:
        api_key = get_serpapi_key()
        
        # Build search parameters
        params = {
            "engine": "google_hotels",
            "q": location,
            "check_in_date": check_in_date,
            "check_out_date": check_out_date,
            "adults": adults,
            "children": children,
            "currency": currency,
            "gl": country,
            "hl": language,
            "api_key": api_key
        }
        
        # Add optional parameters
        if children_ages:
            params["children_ages"] = ",".join(map(str, children_ages))
        if sort_by:
            params["sort_by"] = sort_by
        if hotel_class:
            params["hotel_class"] = ",".join(map(str, hotel_class))
        if amenities:
            params["amenities"] = ",".join(map(str, amenities))
        if property_types:
            params["property_types"] = ",".join(map(str, property_types))
        if brands:
            params["brands"] = ",".join(map(str, brands))
        if free_cancellation:
            params["free_cancellation"] = "true"
        if special_offers:
            params["special_offers"] = "true"
        if vacation_rentals:
            params["vacation_rentals"] = "true"
        if bedrooms:
            params["bedrooms"] = bedrooms
            
        # Make API request
        response = requests.get("https://serpapi.com/search", params=params)
        response.raise_for_status()
        
        hotel_data = response.json()
        
        # Process hotel results
        processed_results = {
            "provider": "Google Hotels (SerpAPI)",
            "search_metadata": {
                "location": location,
                "check_in_date": check_in_date,
                "check_out_date": check_out_date,
                "guests": {
                    "adults": adults,
                    "children": children,
                    "children_ages": children_ages or []
                },
                "currency": currency,
                "search_timestamp": datetime.now().isoformat()
            },
            "properties": hotel_data.get("properties", [])[:max_results],
            "filters": hotel_data.get("filters", {}),
            "search_parameters": hotel_data.get("search_parameters", {}),
            "location_info": hotel_data.get("place_results", {})
        }
        
        return processed_results
        
    except requests.exceptions.RequestException as e:
        return {"error": f"Google Hotels API request failed: {str(e)}"}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}

@mcp.tool()
def search_hotels_amadeus_by_city(
    cityCode: str,
    ctx: Context,
    radius: int = None,
    radiusUnit: str = None,
    chainCodes: str = None,
    amenities: str = None,
    ratings: str = None,
    hotelSource: str = None
) -> str:
    """
    🏨 Discover professional hotel listings using Amadeus! Find accommodations that match your style, budget, and preferences using the same system travel professionals use.

    This tool provides access to Amadeus's comprehensive hotel database with detailed property information and professional booking capabilities.

    Args:
        cityCode: IATA code of the city (e.g., PAR for Paris, NYC for New York)
        radius: Search radius from city center (default depends on city size)
        radiusUnit: Unit for radius (KM for kilometers, MI for miles)
        chainCodes: Comma-separated hotel chain codes (e.g., MC,RT,EZ)
        amenities: Comma-separated amenity codes (e.g., SPA,WIFI,POOL)
        ratings: Comma-separated hotel ratings (1,2,3,4,5)
        hotelSource: Source of hotel content (ALL, BEDBANK, etc.)
    """
    amadeus_client = ctx.request_context.lifespan_context.amadeus_client
    params = {"cityCode": cityCode}
    
    if radius is not None:
        params["radius"] = radius
    if radiusUnit:
        params["radiusUnit"] = radiusUnit
    if chainCodes:
        params["chainCodes"] = chainCodes
    if amenities:
        params["amenities"] = amenities
    if ratings:
        params["ratings"] = ratings
    if hotelSource:
        params["hotelSource"] = hotelSource
    
    try:
        ctx.info(f"Searching Amadeus hotels in city: {cityCode}")
        ctx.info(f"API parameters: {json.dumps(params)}")
        
        response = amadeus_client.reference_data.locations.hotels.by_city.get(**params)
        result = response.body
        result["provider"] = "Amadeus GDS"
        result["search_timestamp"] = datetime.now().isoformat()
        return json.dumps(result)
    except ResponseError as error:
        error_msg = f"Amadeus API error: {str(error)}"
        ctx.info(f"Error: {error_msg}")
        return json.dumps({"error": error_msg})
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        ctx.info(f"Error: {error_msg}")
        return json.dumps({"error": error_msg})

@mcp.tool()
def search_hotels_amadeus_geocode(
    latitude: float,
    longitude: float,
    ctx: Context,
    radius: int = None,
    radiusUnit: str = None,
    chainCodes: str = None,
    amenities: str = None,
    ratings: str = None,
    hotelSource: str = None
) -> str:
    """
    🎯 Find hotels near any specific location with pinpoint accuracy using Amadeus! Perfect for finding accommodations near landmarks, airports, business districts, or any precise location.

    Args:
        latitude: Latitude of the location (e.g., 48.8566 for Paris)
        longitude: Longitude of the location (e.g., 2.3522 for Paris)
        radius: Search radius from coordinates (default depends on area)
        radiusUnit: Unit for radius (KM for kilometers, MI for miles)
        chainCodes: Comma-separated hotel chain codes (e.g., MC,RT,EZ)
        amenities: Comma-separated amenity codes (e.g., SPA,WIFI,POOL)
        ratings: Comma-separated hotel ratings (1,2,3,4,5)
        hotelSource: Source of hotel content (ALL, BEDBANK, etc.)
    """
    amadeus_client = ctx.request_context.lifespan_context.amadeus_client
    params = {"latitude": latitude, "longitude": longitude}
    
    if radius is not None:
        params["radius"] = radius
    if radiusUnit:
        params["radiusUnit"] = radiusUnit
    if chainCodes:
        params["chainCodes"] = chainCodes
    if amenities:
        params["amenities"] = amenities
    if ratings:
        params["ratings"] = ratings
    if hotelSource:
        params["hotelSource"] = hotelSource
    
    try:
        ctx.info(f"Searching Amadeus hotels at coordinates: {latitude}, {longitude}")
        ctx.info(f"API parameters: {json.dumps(params)}")
        
        response = amadeus_client.reference_data.locations.hotels.by_geocode.get(**params)
        result = response.body
        result["provider"] = "Amadeus GDS"
        result["search_timestamp"] = datetime.now().isoformat()
        return json.dumps(result)
    except ResponseError as error:
        error_msg = f"Amadeus API error: {str(error)}"
        ctx.info(f"Error: {error_msg}")
        return json.dumps({"error": error_msg})
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        ctx.info(f"Error: {error_msg}")
        return json.dumps({"error": error_msg})

@mcp.tool()
def search_hotel_offers_amadeus(
    ctx: Context,
    cityCode: str = None,
    hotelIds: str = None,
    checkInDate: str = None,
    checkOutDate: str = None,
    adults: int = 1,
    roomQuantity: int = None,
    priceRange: str = None,
    currency: str = None,
    paymentPolicy: str = None,
    boardType: str = None,
    includeClosed: bool = None,
    bestRateOnly: bool = None,
    view: str = None,
    sort: str = None,
    lang: str = None
) -> str:
    """
    💰 Find the best hotel deals with real-time pricing and availability using Amadeus! Search for actual bookable rates and room availability for your exact travel dates.

    Args:
        cityCode: IATA code of the city (e.g., PAR for Paris) - required if hotelIds not provided
        hotelIds: Comma-separated list of hotel IDs - required if cityCode not provided
        checkInDate: Check-in date in YYYY-MM-DD format
        checkOutDate: Check-out date in YYYY-MM-DD format  
        adults: Number of adult guests (default: 1)
        roomQuantity: Number of rooms requested (default: 1)
        priceRange: Price range filter (e.g., 50-200)
        currency: Currency code for prices (e.g., USD, EUR)
        paymentPolicy: Payment policy (GUARANTEE, DEPOSIT, NONE)
        boardType: Board type (ROOM_ONLY, BREAKFAST, HALF_BOARD, FULL_BOARD, ALL_INCLUSIVE)
        includeClosed: Include temporarily closed hotels (true/false)
        bestRateOnly: Return only the best rate per hotel (true/false)
        view: Response view (FULL, LIGHT)
        sort: Sort order (PRICE, NONE)
        lang: Language code for descriptions (e.g., EN, FR)
    """
    if not cityCode and not hotelIds:
        return json.dumps({"error": "Either cityCode or hotelIds must be provided"})
    
    amadeus_client = ctx.request_context.lifespan_context.amadeus_client
    params = {"adults": adults}
    
    if cityCode:
        params["cityCode"] = cityCode
    if hotelIds:
        params["hotelIds"] = hotelIds
    if checkInDate:
        params["checkInDate"] = checkInDate
    if checkOutDate:
        params["checkOutDate"] = checkOutDate
    if roomQuantity is not None:
        params["roomQuantity"] = roomQuantity
    if priceRange:
        params["priceRange"] = priceRange
    if currency:
        params["currency"] = currency
    if paymentPolicy:
        params["paymentPolicy"] = paymentPolicy
    if boardType:
        params["boardType"] = boardType
    if includeClosed is not None:
        params["includeClosed"] = includeClosed
    if bestRateOnly is not None:
        params["bestRateOnly"] = bestRateOnly
    if view:
        params["view"] = view
    if sort:
        params["sort"] = sort
    if lang:
        params["lang"] = lang
    
    try:
        search_location = cityCode if cityCode else f"hotels {hotelIds}"
        ctx.info(f"Searching Amadeus hotel offers for: {search_location}")
        ctx.info(f"API parameters: {json.dumps(params)}")
        
        response = amadeus_client.shopping.hotel_offers.get(**params)
        result = response.body
        result["provider"] = "Amadeus GDS"
        result["search_timestamp"] = datetime.now().isoformat()
        return json.dumps(result)
    except ResponseError as error:
        error_msg = f"Amadeus API error: {str(error)}"
        ctx.info(f"Error: {error_msg}")
        return json.dumps({"error": error_msg})
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        ctx.info(f"Error: {error_msg}")
        return json.dumps({"error": error_msg})

# =====================================================================
# COMBINED ACTIVITY & EVENT SEARCH TOOLS
# =====================================================================

@mcp.tool()
def search_events_serpapi(
    query: str,
    location: Optional[str] = None,
    date_filter: Optional[str] = None,
    event_type: Optional[str] = None,
    language: str = "en",
    country: str = "us",
    max_results: int = 20
) -> Dict[str, Any]:
    """
    🎭 Discover amazing experiences and events using Google Events! Your AI travel concierge will find the perfect activities, shows, festivals, and cultural experiences to enrich your journey.
    
    Whether you're seeking Broadway shows, local festivals, art exhibitions, concerts, food events, or unique cultural experiences, I'll uncover the best events happening during your visit.
    
    Args:
        query: What type of experiences you're seeking (e.g., "concerts", "food festivals", "art galleries", "theater")
        location: Where you'll be exploring (e.g., "Manhattan NYC", "Paris Marais", "Tokyo Shibuya")
        date_filter: When you want to experience events (today, tomorrow, week, weekend, next_week, month, next_month)
        event_type: Type of experience (Virtual-Event for online events you can enjoy from anywhere)
        language: Your preferred language for event information
        country: Your country for localized event discovery
        max_results: Maximum number of amazing events to show you
        
    Returns:
        Curated list of exciting events and experiences with details, timing, and booking information
    """
    
    try:
        api_key = get_serpapi_key()
        
        # Build search query
        search_query = query
        if location:
            search_query += f" in {location}"
        
        # Build search parameters
        params = {
            "engine": "google_events",
            "q": search_query,
            "hl": language,
            "gl": country,
            "api_key": api_key
        }
        
        # Add optional filters
        if date_filter:
            params["htichips"] = f"date:{date_filter}"
        if event_type:
            params["htichips"] = f"event_type:{event_type}"
        
        # Make API request
        response = requests.get("https://serpapi.com/search", params=params)
        response.raise_for_status()
        
        event_data = response.json()
        
        # Process event results
        processed_results = {
            "provider": "Google Events (SerpAPI)",
            "search_metadata": {
                "query": query,
                "location": location,
                "date_filter": date_filter,
                "event_type": event_type,
                "language": language,
                "country": country,
                "search_timestamp": datetime.now().isoformat()
            },
            "events": event_data.get("events_results", [])[:max_results],
            "search_parameters": event_data.get("search_parameters", {})
        }
        
        return processed_results
        
    except requests.exceptions.RequestException as e:
        return {"error": f"Google Events API request failed: {str(e)}"}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}

@mcp.tool()
def search_activities_amadeus(
    latitude: float,
    longitude: float,
    ctx: Context,
    radius: int = None,
    radiusUnit: str = "KM"
) -> str:
    """
    🎭 Discover amazing tours and activities using Amadeus! Find tours, attractions, and unique experiences to make your trip unforgettable.

    This tool provides access to Amadeus's curated activity database with professional tour operators and verified experiences.

    Args:
        latitude: Location latitude (e.g., 48.8566 for Paris center)
        longitude: Location longitude (e.g., 2.3522 for Paris center)
        radius: Search area radius (default: 1km for city centers, increase for wider searches)
        radiusUnit: Distance unit ('KM' for kilometers, 'MI' for miles)
        
    Returns:
        Curated list of tours, activities, and experiences with descriptions and booking information
    """
    amadeus_client = ctx.request_context.lifespan_context.amadeus_client
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "radius": radius or 1,
        "radiusUnit": radiusUnit
    }
    
    try:
        ctx.info(f"Searching Amadeus tours and activities at coordinates: {latitude}, {longitude}")
        ctx.info(f"API parameters: {json.dumps(params)}")
        
        # Note: This endpoint might be available in newer versions of the Amadeus SDK
        response = amadeus_client.shopping.activities.get(**params)
        result = response.body
        result["provider"] = "Amadeus GDS"
        result["search_timestamp"] = datetime.now().isoformat()
        return json.dumps(result)
    except ResponseError as error:
        error_msg = f"Amadeus API error: {str(error)}"
        ctx.info(f"Error: {error_msg}")
        return json.dumps({"error": error_msg})
    except AttributeError as e:
        error_msg = f"Tours and Activities API not available in current SDK version: {str(e)}"
        ctx.info(f"Error: {error_msg}")
        return json.dumps({"error": error_msg, "note": "This API might require a newer SDK version or special access"})
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        ctx.info(f"Error: {error_msg}")
        return json.dumps({"error": error_msg})

@mcp.tool()
def get_activity_details_amadeus(
    activityId: str,
    ctx: Context
) -> str:
    """
    🎆 Get complete details about a specific activity using Amadeus! Perfect for when you've found something interesting and want full information before booking.

    Args:
        activityId: The unique ID of the activity you're interested in
        
    Returns:
        Complete activity details with schedules, pricing, requirements, and booking information
    """
    amadeus_client = ctx.request_context.lifespan_context.amadeus_client
    
    try:
        ctx.info(f"Getting Amadeus activity details for: {activityId}")
        
        response = amadeus_client.shopping.activity(activityId).get()
        result = response.body
        result["provider"] = "Amadeus GDS"
        result["search_timestamp"] = datetime.now().isoformat()
        return json.dumps(result)
    except ResponseError as error:
        error_msg = f"Amadeus API error: {str(error)}"
        ctx.info(f"Error: {error_msg}")
        return json.dumps({"error": error_msg})
    except AttributeError as e:
        error_msg = f"Tours and Activities API not available in current SDK version: {str(e)}"
        ctx.info(f"Error: {error_msg}")
        return json.dumps({"error": error_msg, "note": "This API might require a newer SDK version or special access"})
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        ctx.info(f"Error: {error_msg}")
        return json.dumps({"error": error_msg})

# =====================================================================
# GEOCODING TOOLS
# =====================================================================

@mcp.tool()
def geocode_location(
    location: str,
    exactly_one: bool = True,
    timeout: int = 10,
    language: str = "en",
    addressdetails: bool = True,
    country_codes: Optional[str] = None
) -> Dict[str, Any]:
    """
    🌍 Pinpoint any destination on Earth with precision! Convert any location name, address, or landmark into exact coordinates for perfect trip planning.
    
    Args:
        location: Any place you want to locate (e.g., "Eiffel Tower", "Times Square NYC", "Santorini Greece")
        exactly_one: True for the best match, False to see multiple location options
        timeout: How long to search for the location (in seconds)
        language: Your preferred language for location details
        addressdetails: True to get complete address breakdown and local information
        country_codes: Limit search to specific countries (e.g., "us,ca" for US and Canada only)
        
    Returns:
        Precise coordinates and comprehensive location details for your travel planning
    """
    
    try:
        geocode, _ = get_geolocator()
        
        # Build geocoding parameters
        geocode_params = {
            "exactly_one": exactly_one,
            "timeout": timeout,
            "language": language,
            "addressdetails": addressdetails
        }
        
        if country_codes:
            geocode_params["country_codes"] = country_codes.split(",")
        
        # Perform geocoding
        result = geocode(location, **geocode_params)
        
        if not result:
            return {
                "error": f"Location '{location}' not found",
                "suggestions": "Try using a more specific address or well-known landmark name"
            }
        
        # Process results
        if exactly_one:
            processed_result = {
                "location": location,
                "coordinates": {
                    "latitude": float(result.latitude),
                    "longitude": float(result.longitude)
                },
                "address": result.address,
                "raw_data": result.raw,
                "search_timestamp": datetime.now().isoformat()
            }
        else:
            processed_result = {
                "location": location,
                "multiple_results": [
                    {
                        "coordinates": {
                            "latitude": float(r.latitude),
                            "longitude": float(r.longitude)
                        },
                        "address": r.address,
                        "raw_data": r.raw
                    } for r in result
                ],
                "search_timestamp": datetime.now().isoformat()
            }
        
        return processed_result
        
    except (GeocoderTimedOut, GeocoderUnavailable) as e:
        return {"error": f"Geocoding service error: {str(e)}"}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}

@mcp.tool()
def calculate_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    unit: str = "km"
) -> Dict[str, Any]:
    """
    📏 Measure distances between any two places on Earth! Perfect for planning travel routes and optimizing your itinerary.
    
    Args:
        lat1: Latitude of your first location
        lon1: Longitude of your first location  
        lat2: Latitude of your destination
        lon2: Longitude of your destination
        unit: Your preferred distance unit ("km" for kilometers, "miles" for miles, "nm" for nautical miles)
        
    Returns:
        Precise distance measurements to help you plan travel times and routes
    """
    
    try:
        from geopy.distance import geodesic
        
        point1 = (lat1, lon1)
        point2 = (lat2, lon2)
        
        # Calculate distance
        distance = geodesic(point1, point2)
        
        # Convert to requested unit
        if unit.lower() == "miles":
            distance_value = distance.miles
        elif unit.lower() == "nm":
            distance_value = distance.nautical
        else:  # default to kilometers
            distance_value = distance.kilometers
        
        result = {
            "point1": {"latitude": lat1, "longitude": lon1},
            "point2": {"latitude": lat2, "longitude": lon2},
            "distance": {
                "value": round(distance_value, 2),
                "unit": unit.lower()
            },
            "all_units": {
                "kilometers": round(distance.kilometers, 2),
                "miles": round(distance.miles, 2),
                "nautical_miles": round(distance.nautical, 2)
            },
            "calculation_timestamp": datetime.now().isoformat()
        }
        
        return result
        
    except Exception as e:
        return {"error": f"Distance calculation error: {str(e)}"}

# =====================================================================
# WEATHER TOOLS
# =====================================================================

OPEN_METEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"

@mcp.tool()
def get_current_conditions(latitude: float, longitude: float) -> Dict[str, Any]:
    """
    🌤️ Get real-time weather conditions for your destination using Open-Meteo.
    
    Args:
        latitude: Latitude of your destination
        longitude: Longitude of your destination
        
    Returns:
        Current weather with temperature, wind, and conditions
    """
    try:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current_weather": "true",
            "timezone": "auto",
        }
        response = requests.get(OPEN_METEO_BASE_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        current = data.get("current_weather") or data.get("current")
        if not current:
            return {"error": "Current weather not available"}

        result = {
            "coordinates": {"latitude": latitude, "longitude": longitude},
            "provider": "open-meteo",
            "current_conditions": {
                "timestamp": current.get("time"),
                "temperature_c": current.get("temperature"),
                "windspeed_kph": current.get("windspeed"),
                "winddirection_deg": current.get("winddirection"),
                "is_day": current.get("is_day"),
                "weathercode": current.get("weathercode"),
            },
            "search_timestamp": datetime.now().isoformat(),
        }
        return result
    except requests.exceptions.RequestException as e:
        return {"error": f"Weather API request failed: {str(e)}"}
    except Exception as e:
        return {"error": f"Error processing weather data: {str(e)}"}

@mcp.tool()
def get_weather_forecast(latitude: float, longitude: float, hourly: bool = False) -> Dict[str, Any]:
    """
    🌦️ Plan your trip with detailed weather forecasts using Open-Meteo.
    
    Args:
        latitude: Latitude of your destination
        longitude: Longitude of your destination
        hourly: True for hourly forecast, False for daily summary
    """
    try:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "timezone": "auto",
        }
        if hourly:
            params["hourly"] = ",".join([
                "temperature_2m",
                "relative_humidity_2m",
                "apparent_temperature",
                "precipitation_probability",
                "windspeed_10m",
                "winddirection_10m",
                "weathercode",
            ])
        else:
            params["daily"] = ",".join([
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
                "sunrise",
                "sunset",
                "uv_index_max",
            ])

        response = requests.get(OPEN_METEO_BASE_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        result_periods: List[Dict[str, Any]] = []
        if hourly:
            hourly_data = data.get("hourly", {})
            times = hourly_data.get("time", [])
            for idx, t in enumerate(times):
                result_periods.append({
                    "time": t,
                    "temperature_c": (hourly_data.get("temperature_2m") or [None])[idx] if idx < len(hourly_data.get("temperature_2m", [])) else None,
                    "relative_humidity": (hourly_data.get("relative_humidity_2m") or [None])[idx] if idx < len(hourly_data.get("relative_humidity_2m", [])) else None,
                    "apparent_temperature_c": (hourly_data.get("apparent_temperature") or [None])[idx] if idx < len(hourly_data.get("apparent_temperature", [])) else None,
                    "precipitation_probability": (hourly_data.get("precipitation_probability") or [None])[idx] if idx < len(hourly_data.get("precipitation_probability", [])) else None,
                    "windspeed_10m": (hourly_data.get("windspeed_10m") or [None])[idx] if idx < len(hourly_data.get("windspeed_10m", [])) else None,
                    "winddirection_10m": (hourly_data.get("winddirection_10m") or [None])[idx] if idx < len(hourly_data.get("winddirection_10m", [])) else None,
                    "weathercode": (hourly_data.get("weathercode") or [None])[idx] if idx < len(hourly_data.get("weathercode", [])) else None,
                })
            units = data.get("hourly_units", {})
            forecast_meta = {"units": units}
        else:
            daily_data = data.get("daily", {})
            times = daily_data.get("time", [])
            for idx, t in enumerate(times):
                result_periods.append({
                    "date": t,
                    "temp_max_c": (daily_data.get("temperature_2m_max") or [None])[idx] if idx < len(daily_data.get("temperature_2m_max", [])) else None,
                    "temp_min_c": (daily_data.get("temperature_2m_min") or [None])[idx] if idx < len(daily_data.get("temperature_2m_min", [])) else None,
                    "precipitation_sum_mm": (daily_data.get("precipitation_sum") or [None])[idx] if idx < len(daily_data.get("precipitation_sum", [])) else None,
                    "sunrise": (daily_data.get("sunrise") or [None])[idx] if idx < len(daily_data.get("sunrise", [])) else None,
                    "sunset": (daily_data.get("sunset") or [None])[idx] if idx < len(daily_data.get("sunset", [])) else None,
                    "uv_index_max": (daily_data.get("uv_index_max") or [None])[idx] if idx < len(daily_data.get("uv_index_max", [])) else None,
                })
            units = data.get("daily_units", {})
            forecast_meta = {"units": units}

        result = {
            "coordinates": {"latitude": latitude, "longitude": longitude},
            "provider": "open-meteo",
            "forecast_type": "hourly" if hourly else "daily",
            "forecast_periods": result_periods,
            "forecast_metadata": forecast_meta,
            "search_timestamp": datetime.now().isoformat(),
        }
        return result
    except requests.exceptions.RequestException as e:
        return {"error": f"Weather API request failed: {str(e)}"}
    except Exception as e:
        return {"error": f"Error processing forecast data: {str(e)}"}

# =====================================================================
# FINANCIAL TOOLS
# =====================================================================

@mcp.tool()
def convert_currency(
    from_currency: str,
    to_currency: str,
    amount: float = 1.0,
    language: str = "en"
) -> Dict[str, Any]:
    """
    💱 Real-time currency conversion using ExchangeRate-API.
    
    Args:
        from_currency: Source currency code (e.g., 'USD')
        to_currency: Target currency code (e.g., 'EUR')
        amount: Amount to convert (default: 1.0)
        language: Unused; kept for compatibility
    """
    try:
        api_key = get_exchange_rate_api_key()
        base_url = f"https://v6.exchangerate-api.com/v6/{api_key}/pair/{from_currency.upper()}/{to_currency.upper()}"
        response = requests.get(base_url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("result") != "success":
            return {"error": data.get("error-type") or "ExchangeRate-API error"}

        rate = data.get("conversion_rate")
        if rate is None:
            return {"error": "Conversion rate not available"}

        converted_amount = round(amount * float(rate), 2)

        processed_results = {
            "search_metadata": {
                "from_currency": from_currency.upper(),
                "to_currency": to_currency.upper(),
                "amount": amount,
                "search_timestamp": datetime.now().isoformat(),
                "provider": "exchangerate-api",
            },
            "exchange_rate": rate,
            "conversion": {
                "original_amount": amount,
                "converted_amount": converted_amount,
                "rate": rate,
            },
        }
        return processed_results
    except requests.exceptions.RequestException as e:
        return {"error": f"Currency API request failed: {str(e)}"}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}

@mcp.tool()
def lookup_stock(
    symbol: str,
    exchange: Optional[str] = None,
    window: Optional[str] = None,
    language: str = "en"
) -> Dict[str, Any]:
    """
    📈 Track travel investments and monitor travel-related stocks! Stay informed about airline stocks, hotel chains, travel companies, and tourism-related investments.
    
    Args:
        symbol: Stock symbol of travel companies (e.g., 'DAL' for Delta, 'MAR' for Marriott, 'BKNG' for Booking Holdings)
        exchange: Stock exchange if specific (e.g., 'NASDAQ', 'NYSE', 'LSE')
        window: Historical data timeframe ('1D', '5D', '1M', '6M', '1Y', '5Y', 'MAX')
        language: Your preferred language for financial information
        
    Returns:
        Comprehensive stock analysis with pricing, trends, and investment insights
    """
    
    try:
        api_key = get_serpapi_key()
        
        # Format query
        query = symbol.upper()
        if exchange:
            query = f"{symbol.upper()}:{exchange.upper()}"
        
        # Build search parameters
        params = {
            "engine": "google_finance",
            "q": query,
            "hl": language,
            "api_key": api_key
        }
        
        if window:
            params["window"] = window
        
        # Make API request
        response = requests.get("https://serpapi.com/search", params=params)
        response.raise_for_status()
        
        finance_data = response.json()
        
        # Process results
        processed_results = {
            "search_metadata": {
                "symbol": symbol.upper(),
                "exchange": exchange,
                "window": window,
                "language": language,
                "search_timestamp": datetime.now().isoformat()
            },
            "stock_info": finance_data.get("summary", {}),
            "price_movement": finance_data.get("price_movement", {}),
            "historical_data": finance_data.get("historical_data", []),
            "news": finance_data.get("news", [])
        }
        
        return processed_results
        
    except requests.exceptions.RequestException as e:
        return {"error": f"API request failed: {str(e)}"}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}

# =====================================================================
# UNIFIED PROMPTS
# =====================================================================

@mcp.prompt()
def travel_planning_prompt(
    destination: str,
    departure_location: str = "",
    travel_dates: str = "",
    travelers: int = 1,
    budget: str = "",
    interests: str = "",
    travel_style: str = ""
) -> str:
    """🌟 Your Complete Combined AI Travel Concierge - Trip Planning Assistant"""
    
    prompt = f"""🌟 **WELCOME TO YOUR COMBINED TRAVEL CONCIERGE SERVICE** 🌟

I'm your comprehensive AI travel specialist with access to BOTH Google Travel Services AND Amadeus Professional Systems! Let me plan your perfect journey to {destination}"""
    
    if departure_location:
        prompt += f" from {departure_location}"
    
    if travel_dates:
        prompt += f" for {travel_dates}"
    
    prompt += f" for {travelers} traveler{'s' if travelers != 1 else ''}."
    
    if budget:
        prompt += f"\n💰 **Budget**: {budget}"
    
    if interests:
        prompt += f"\n🎯 **Your Interests**: {interests}"
    
    if travel_style:
        prompt += f"\n✈️ **Travel Style**: {travel_style}"
    
    prompt += f"""

🎪 **YOUR COMPLETE DUAL-POWERED TRAVEL EXPERIENCE:**

✈️ **PHASE 1: Flight Discovery & Comparison**
   🌐 **Google Flights Search** - Use search_flights_serpapi() for comprehensive consumer flight options
   🏢 **Amadeus Professional Search** - Use search_flights_amadeus() for professional airline inventory
   • Compare results from both systems to find the absolute best deals
   • Access both consumer-friendly Google results AND professional travel agent data
   • Get price insights, schedule optimization, and booking flexibility options

🏨 **PHASE 2: Hotel & Accommodation Discovery**
   🌐 **Google Hotels Search** - Use search_hotels_serpapi() for comprehensive accommodation options
   🏢 **Amadeus Hotel Search** - Use search_hotels_amadeus_by_city() or search_hotels_amadeus_by_geocode()
   🏨 **Professional Hotel Offers** - Use search_hotel_offers_amadeus() for real-time availability and pricing
   • Access vacation rentals, boutique hotels, and major chains through Google
   • Get professional rates and detailed property information through Amadeus
   • Compare pricing and availability across both platforms

🎭 **PHASE 3: Events & Activities Discovery**
   🌐 **Google Events** - Use search_events_serpapi() for local events, concerts, festivals
   🏢 **Amadeus Activities** - Use search_tours_activities_amadeus() for professional tour operations
   • Find everything from local festivals to professional guided tours
   • Access both consumer events and curated travel experiences

🌍 **PHASE 4: Location Intelligence & Navigation**
   • Use geocode_location() to pinpoint exact coordinates for all destinations
   • Use calculate_distance() to optimize your itinerary and travel routes
   • Map out efficient daily routes between attractions, hotels, and activities

🌦️ **PHASE 5: Weather Intelligence & Activity Planning**
   • Use get_weather_forecast() to understand conditions during your visit
   • Use get_current_conditions() for real-time weather updates
   • Plan activities around optimal weather windows

💰 **PHASE 6: Financial Planning & Currency Strategy**
   • Use convert_currency() for accurate budget planning and expense tracking
   • Use lookup_stock() to monitor travel industry investments if relevant
   • Track exchange rates and optimize currency conversion timing

🎨 **PRESENTATION STYLE**: 
Present everything as your expert travel friend who has access to BOTH consumer travel platforms AND professional travel industry systems! Provide detailed comparisons, insider tips, and create comprehensive travel plans.

**AVAILABLE DUAL-PLATFORM TOOLS:**

**✈️ FLIGHT SEARCH:**
- 🌐 search_flights_serpapi() - Google Flights consumer search
- 🏢 search_flights_amadeus() - Amadeus professional GDS search

**🏨 HOTEL SEARCH:**
- 🌐 search_hotels_serpapi() - Google Hotels consumer search
- 🏢 search_hotels_amadeus_by_city() - Amadeus professional city search
- 🏢 search_hotels_amadeus_by_geocode() - Amadeus professional coordinate search
- 🏢 search_hotel_offers_amadeus() - Amadeus real-time offers and availability

**🎭 EVENTS & ACTIVITIES:**
- 🌐 search_events_serpapi() - Google Events consumer search
- 🏢 search_tours_activities_amadeus() - Amadeus professional activities
- 🏢 get_activity_details_amadeus() - Detailed activity information

**🌍 LOCATION & UTILITIES:**
- geocode_location() - Precise location finding
- calculate_distance() - Route optimization
- get_weather_forecast() - Weather planning
- get_current_conditions() - Real-time weather
- convert_currency() - Financial planning
- lookup_stock() - Travel investment tracking

Let's create your perfect travel experience using BOTH consumer and professional travel platforms! 🌎✨"""

    return prompt

@mcp.resource("travel://combined/capabilities")
def combined_travel_server_capabilities() -> str:
    """🌟 Complete Guide to Your Combined Travel Concierge Server Capabilities"""
    
    return """# 🌟 Combined Travel Concierge Server - Complete Capabilities Guide

## Overview
This combined server integrates the best of both consumer travel platforms (Google via SerpAPI) AND professional travel industry systems (Amadeus GDS) into one powerful platform, providing unparalleled travel planning assistance.

## ✈️ Dual Flight Search Services

### 🌐 Consumer Flight Search (Google Flights via SerpAPI)
**Tool:** `search_flights_serpapi()`
- Access Google's comprehensive flight database
- Consumer-friendly pricing and schedule display
- Price insights and trend analysis
- Multi-airline comparison with popular routes
- Family-friendly search with children and infant options

### 🏢 Professional Flight Search (Amadeus GDS)
**Tool:** `search_flights_amadeus()`
- Professional travel agent inventory access
- Real-time airline seat availability
- Detailed fare class information
- Professional booking codes and restrictions
- Advanced filtering by airline preferences

**Combined Benefits:**
- Compare consumer vs. professional pricing
- Access both popular routes AND hidden inventory
- Get comprehensive view of all available options
- Professional insights with consumer-friendly presentation

## 🏨 Comprehensive Hotel Services

### 🌐 Consumer Hotel Search (Google Hotels via SerpAPI)
**Tool:** `search_hotels_serpapi()`
- Vacation rentals, boutique hotels, major chains
- Consumer reviews and ratings
- Special offers and package deals
- Family-friendly filtering with children's ages
- Flexible cancellation and booking options

### 🏢 Professional Hotel Search (Amadeus GDS)
**Tools:** 
- `search_hotels_amadeus_by_city()` - City-based professional search
- `search_hotels_amadeus_by_geocode()` - Coordinate-based search
- `search_hotel_offers_amadeus()` - Real-time availability and pricing

**Professional Features:**
- Travel industry rates and inventory
- Real-time room availability
- Professional booking codes
- Detailed property amenities and chain information
- Business travel optimized results

## 🎭 Dual Event & Activity Discovery

### 🌐 Consumer Events (Google Events via SerpAPI)
**Tool:** `search_events_serpapi()`
- Local festivals, concerts, exhibitions
- Consumer-friendly event discovery
- Popular attractions and entertainment
- Virtual events and online experiences

### 🏢 Professional Activities (Amadeus GDS)
**Tools:**
- `search_tours_activities_amadeus()` - Professional tour operations
- `get_activity_details_amadeus()` - Detailed activity information

**Professional Features:**
- Curated tour operators and experiences
- Professional activity bookings
- Verified experience providers
- Detailed scheduling and requirements

## 🌍 Location Intelligence Services
**Tools Available:**
- `geocode_location()` - Convert addresses/places to coordinates
- `calculate_distance()` - Measure distances between locations

**Capabilities:**
- Precise location identification worldwide
- Distance calculations for route optimization
- Multi-language location details
- Address detail breakdown

## 🌦️ Weather Intelligence Service
**Tools Available:**
- `get_weather_forecast()` - Detailed weather forecasts
- `get_current_conditions()` - Real-time weather data

**Capabilities:**
- Daily and hourly weather forecasts using Open-Meteo
- Current temperature, humidity, wind conditions
- Activity planning based on weather conditions
- Travel safety considerations

## 💰 Financial Services
**Tools Available:**
- `convert_currency()` - Real-time currency conversion via ExchangeRate-API
- `lookup_stock()` - Travel industry stock monitoring via Google Finance

**Capabilities:**
- Real-time exchange rates for international travel
- Travel industry investment tracking
- Budget planning assistance across currencies
- Financial market insights for travel investments

## 🎯 Unified Planning Advantages

**Dual Platform Benefits:**
- **Best Price Discovery**: Compare consumer vs. professional rates
- **Maximum Inventory Access**: See both popular and hidden options
- **Professional + Consumer Insights**: Get industry knowledge with user-friendly presentation
- **Comprehensive Coverage**: Access the widest range of travel options available
- **Redundancy & Reliability**: If one platform has issues, the other provides backup

**Integration Benefits:**
- Single server handles all travel needs across multiple platforms
- Coordinated data sharing between consumer and professional services
- Unified error handling and comprehensive reporting
- Consistent API responses across all services

## 🔧 Technical Specifications

**Required Environment Variables:**
- `SERPAPI_KEY` - Required for Google Flights, Hotels, Events, and Finance services
- `AMADEUS_API_KEY` - Required for Amadeus professional services
- `AMADEUS_API_SECRET` - Required for Amadeus professional services
- `EXCHANGE_RATE_API_KEY` - Required for currency conversion services

**Dependencies:**
- requests (API calls)
- geopy (geocoding services)
- amadeus (Amadeus GDS access)
- mcp.server.fastmcp (MCP server framework)

**Error Handling:**
- Graceful API failure handling across all platforms
- Fallback mechanisms between consumer and professional services
- Comprehensive error reporting with platform identification
- Timeout management and rate limiting compliance

## 🚀 Getting Started

1. **Set Environment Variables:**
   ```bash
   export SERPAPI_KEY="your-serpapi-key"
   export AMADEUS_API_KEY="your-amadeus-client-id"
   export AMADEUS_API_SECRET="your-amadeus-client-secret"
   export EXCHANGE_RATE_API_KEY="your-exchangerate-api-key"
   ```

2. **Run the Combined Server:**
   ```bash
   python combined_travel_server.py
   ```

3. **Use the Comprehensive Planning Prompt:**
   Start with `comprehensive_travel_planning_prompt()` for full dual-platform trip planning assistance.

## 🌟 Best Practices for Dual-Platform Usage

**Flight Search Strategy:**
1. Start with Google Flights (search_flights_serpapi) for broad market overview
2. Use Amadeus (search_flights_amadeus) for professional options and detailed fare information
3. Compare results to find the absolute best deals and options

**Hotel Search Strategy:**
1. Use Google Hotels (search_hotels_serpapi) for vacation rentals and consumer-friendly options
2. Use Amadeus hotel searches for professional rates and detailed property information
3. Cross-reference availability and pricing across both platforms

**Activity Planning Strategy:**
1. Use Google Events (search_events_serpapi) for local cultural events and festivals
2. Use Amadeus Activities for professional tours and curated experiences
3. Combine both for comprehensive activity planning

**Location & Weather Integration:**
- Always start with geocoding to establish precise coordinates
- Use weather forecasts to optimize activity and travel planning
- Calculate distances to optimize daily itineraries

**Financial Planning:**
- Use currency conversion for accurate international budget planning
- Monitor travel industry stocks for investment insights
- Track exchange rates for optimal conversion timing

This combined server provides the most comprehensive travel planning capabilities available, leveraging both consumer platforms and professional travel industry systems! 🌎✈️🏨🎭💰"""

if __name__ == "__main__":
    mcp.run()
