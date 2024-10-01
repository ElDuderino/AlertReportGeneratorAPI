import configparser
import logging

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
from io import BytesIO
import base64
import requests
from jinja2 import Template
import weasyprint
import pandas as pd

import plotly.graph_objects as go
import plotly.express as px

import os

from starlette.middleware.cors import CORSMiddleware

from AretasPythonAPI.api_config import APIConfig
from AretasPythonAPI.api_utils import APIUtils
from AretasPythonAPI.aretas_client import APIClient
from AretasPythonAPI.auth import APIAuth
from AretasPythonAPI.building_maps import BuildingMapAPIClient
from AretasPythonAPI.entities import ClientLocationView, Point

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods (GET, POST, PUT, DELETE, etc.)
    allow_headers=["*"],  # Allow all headers
)


def get_building_map(api_auth: APIAuth, location_id, building_map_id, points: list[Point]):
    building_maps = BuildingMapAPIClient(api_auth)

    try:
        image_data = building_maps.get_map_image_with_points(location_id, building_map_id, points)

        if image_data:
            logger.info("Image with points retrieved successfully")
            return image_data
        else:
            logger.error("Failed to retrieve the map image with points.")
            return None

    except Exception as e:
        logger.error(e)
        return None


@app.get("/generate_alert_pdf/{alert_history_record_id}")
async def generate_alert_pdf(alert_history_record_id: int, authorization: Optional[str] = Header(None)):
    logger.info("Attempting to generate AlertHistoryLog pdf")

    if not authorization:
        print("Missing authorization header!")
        raise HTTPException(status_code=401, detail="Authorization header missing")

        # Extract the token from the "Bearer <token>" format
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")

    access_token = authorization.split(" ")[1]

    config = APIConfig('config.cfg')
    api_auth = APIAuth(config, token=access_token)
    client = APIClient(api_auth)

    client_location_view: ClientLocationView = client.get_client_location_view()

    api = APIUtils(api_auth)

    # fetch the Location containing that SensorObject

    # Fetch data
    alert_history_record = api.fetch_alert_history_record(alert_history_record_id)
    alert = api.fetch_alert(alert_history_record.alertId)

    # fetch the SensorObject for that mac
    sensor_obj = client.get_sensor_by_mac(alert_history_record.mac)
    location_obj = client.get_location_by_id(sensor_obj.owner)

    # Calculate times with padding
    alert_time = datetime.fromtimestamp(alert_history_record.timestamp / 1000)
    rtn_time = datetime.fromtimestamp(
        alert_history_record.rtnTimestamp / 1000) if alert_history_record.rtnTimestamp > 0 else datetime.now()
    start_time = int((alert_time - timedelta(hours=1)).timestamp() * 1000)
    end_time = int((rtn_time + timedelta(hours=1)).timestamp() * 1000)

    building_map_img_base64 = None
    has_building_map = False

    if sensor_obj.buildingMapId and len(sensor_obj.buildingMapId) > 0:
        try:
            building_map_img_bytes = get_building_map(
                api_auth,
                location_obj.location.id,
                sensor_obj.buildingMapId,
                [Point(sensor_obj.imgMapX, sensor_obj.imgMapY, 0.0)]
            )
            building_map_img_base64 = base64.b64encode(building_map_img_bytes).decode('utf-8')
            has_building_map = True
        except Exception as e:
            logger.error(e)

    # Fetch chart image
    chart_image_bytes = api.fetch_image_plotly(alert_history_record.mac,
                                               start_time,
                                               end_time,
                                               [alert_history_record.type])

    chart_image_base64 = base64.b64encode(chart_image_bytes).decode('utf-8')

    # Prepare template data
    alert_time_str = alert_time.strftime('%Y-%m-%d %H:%M:%S')
    rtn_time_str = rtn_time.strftime('%Y-%m-%d %H:%M:%S') if alert_history_record.rtnTimestamp > 0 else None

    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Alert Report</title>
        <style>
            body { font-family: Arial, sans-serif; }
            h1 { text-align: center; }
            .section { margin: 20px; }
            .header { background-color: #f0f0f0; padding: 10px; }
            .content { padding: 10px; }
            .image { text-align: center; margin-top: 20px; }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Alert Report</h1>
        </div>
        <div class="section">
            <h2>Alert Details</h2>
            <p><strong>Alert ID:</strong> {{ alert.id }}</p>
            <p><strong>Alert Name:</strong> {{ alert.description }}</p>
            <p><strong>Sensor Type:</strong> {{ alert.sensorType }}</p>
            <p><strong>Alert Threshold:</strong> {{ alert.threshold }}</p>
            <p><strong>Duration:</strong> {{ alert.duration }} seconds</p>
        </div>
        <div class="section">
            <h2>Alert Incident</h2>
            <p><strong>Device MAC:</strong> {{ alert_history.mac }}</p>
            <p><strong>Event ID:</strong> {{ alert_history.eventId }}</p>
            <p><strong>Timestamp:</strong> {{ alert_time }}</p>
            <p><strong>Data:</strong> {{ alert_history.data }}</p>
            <p><strong>Is Active:</strong> {{ alert_history.isActive }}</p>
            {% if rtn_time %}
            <p><strong>Return to Normal Timestamp:</strong> {{ rtn_time }}</p>
            {% endif %}
        </div>
        <div class="section image">
            <h2>Sensor Data Chart</h2>
            <img width="500" height="500" src="data:image/jpeg;base64,{{ chart_image_base64 }}" alt="Sensor Data Chart" />
        </div>
        {% if has_building_map %}
        <div class="section image">
            <h2>Building Map</h2>
            <img width="500" height="500" src="data:image/png;base64,{{ building_map_img_base64 }}" alt="Building Map" />
        </div>
        {% endif %}
    </body>
    </html>
    """

    template = Template(html_template)
    html_content = template.render(
        alert=alert,
        alert_history=alert_history_record,
        alert_time=alert_time_str,
        rtn_time=rtn_time_str,
        chart_image_base64=chart_image_base64,
        has_building_map=has_building_map,
        building_map_img_base64=building_map_img_base64
    )

    # Generate PDF
    pdf = weasyprint.HTML(string=html_content).write_pdf(presentational_hints=True)

    return StreamingResponse(
        BytesIO(pdf),
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=alert_report.pdf"}
    )


logger = logging.getLogger(__name__)

if __name__ == "__main__":
    import uvicorn

    # Only run if this file is executed directly
    uvicorn.run(app, host="0.0.0.0", port=8100, log_level="info")
