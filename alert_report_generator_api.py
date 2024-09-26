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

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods (GET, POST, PUT, DELETE, etc.)
    allow_headers=["*"],  # Allow all headers
)


class AlertHistoryRecord(BaseModel):
    mac: int
    timestamp: int
    type: int
    data: float
    alertId: str
    isActive: bool
    eventId: int
    rtnTimestamp: int


class Alert(BaseModel):
    name: Optional[str] = None
    id: str
    owner: Optional[str] = None
    description: Optional[str] = None
    sensorType: int
    sensorMacs: Optional[str] = None
    backToNormalCommand: Optional[str] = None
    thresholdBEndTime: Optional[float] = None
    thresholdBStartTime: Optional[float] = None
    alertEmails: Optional[str] = None
    durationTrigger: Optional[int] = None
    alertSMSes: Optional[str] = None
    alertTriggerTTL: Optional[int] = None
    alertFrequency: Optional[int] = None
    revision: Optional[str] = None
    maxNumAlerts: Optional[int] = None
    thresholdB: Optional[float] = None
    controlStrategy: Optional[bool] = None
    thresholdA: Optional[float] = None
    thresholdAType: Optional[bool] = None
    thresholdBType: Optional[bool] = None
    disabled: Optional[bool] = None
    exceededCommand: Optional[str] = None


class AretasAPIUtils:

    def __init__(self, access_token: str):
        config = configparser.ConfigParser()
        config.read('config.cfg')
        self.api_base_url = config.get("ARETAS", "api_base_url")
        self.access_token = access_token
        self.logger = logging.getLogger(__name__)

    def fetch_alert_history_record(self, eventId: int, authorization: str) -> AlertHistoryRecord:

        self.logger.info(f"Fetching AlertHistoryRecord for {eventId}")

        url = f"{self.api_base_url}alertlog/getbyeventid?eventId={eventId}"
        headers = {'Authorization': f"Bearer {authorization}"}

        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            # Parse the JSON response into an AlertHistoryRecord model
            return AlertHistoryRecord(**response.json())
        else:
            response.raise_for_status()

    def fetch_alerts(self, authorization: str) -> list[Alert]:
        self.logger.info(f"Fetching alerts")

        url = f"{self.api_base_url}alert/list"
        headers = {'Authorization': f"Bearer {authorization}"}

        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            # Parse the JSON response into a list of Alert models
            return [Alert(**alert) for alert in response.json()]
        else:
            response.raise_for_status()

    def fetch_alert(self, alert_id: str, auth_token: str) -> Alert | None:

        alerts = self.fetch_alerts(auth_token)

        for alert in alerts:
            if alert.id == alert_id:
                return alert

        return None

    def fetch_image_plotly(self, mac, start_timestamp, end_timestamp, sensortypes:list, auth_token):

        self.logger.info(
            f"Fetching sensor data for: mac={mac}, start={start_timestamp}, end={end_timestamp}, sensortypes={sensortypes}")

        url = f"{self.api_base_url}sensordata/byrange"
        headers = {
            "Authorization": f"Bearer {auth_token}"
        }
        params = {
            "mac": mac,
            "begin": start_timestamp,
            "end": end_timestamp,
            "type": sensortypes,
            "limit": 2000000,
            "downsample": False,
            "threshold": 100,
            "movingAverage": False,
            "windowSize": 1,
            "movingAverageType": 0,
            "offsetData": False,
            "requestedIndexes": [0],
            "arrIEQAssumptions": [0],
            "iqRange": -1,
            "interpolateData": False,
            "interpolateTimestep": 30000,
            "interpolateType": 0
        }

        # Fetch the sensor data from the API
        response = requests.get(url, headers=headers, params=params)
        if response.status_code != 200:
            response.raise_for_status()

        # Parse the sensor data
        sensor_data = response.json()

        # Separate the data by type
        data_by_type = {}
        for datum in sensor_data:
            sensor_type = datum['type']
            if sensor_type not in data_by_type:
                data_by_type[sensor_type] = {"timestamps": [], "values": []}

            data_by_type[sensor_type]["timestamps"].append(datum["timestamp"])
            data_by_type[sensor_type]["values"].append(datum["data"])

        # Create a Plotly line chart
        fig = go.Figure()

        for sensor_type, data in data_by_type.items():
            # Convert timestamps from Unix epoch to datetime
            data_frame = pd.DataFrame({
                "timestamp": pd.to_datetime(data["timestamps"], unit='ms'),
                "value": data["values"]
            })

            fig.add_trace(go.Scatter(
                x=data_frame["timestamp"],
                y=data_frame["value"],
                mode='lines',
                name=f'Sensor Type {sensor_type}'
            ))

        # Customize layout
        fig.update_layout(
            title=f"Sensor Data for MAC: {mac}",
            xaxis_title="Time",
            yaxis_title="Sensor Value",
            template="plotly",
            width=800,  # Set your desired width
            height=600,  # Set your desired height
        )

        # Export the plot as a PNG image
        image_bytes = fig.to_image(format="png")

        return image_bytes

    def fetch_chart_image(self, mac, start_timestamp, end_timestamp, sensortype, auth_token):

        self.logger.info(
            f"Fetching chart image for: {mac} start:{start_timestamp} end:{end_timestamp} sensortype:{sensortype}")

        url = f"{self.api_base_url}sensordata/chartimage"
        headers = {
            "Authorization": f"Bearer {auth_token}"
        }
        params = {
            "mac": mac,
            "begin": start_timestamp,
            "end": end_timestamp,
            "type": [sensortype],
            "width": 640,  # default value
            "height": 480,  # default value
            "limit": 2000000,
            "downsample": False,
            "threshold": 100,
            "movingAverage": False,
            "windowSize": 1,
            "movingAverageType": 0,
            "offsetData": False,
            "requestedIndexes": [0],  # default value
            "arrIEQAssumptions": [0],  # default value
            "iqRange": -1,
            "interpolateData": False,
            "interpolateTimestep": 30000,
            "interpolateType": 0
        }

        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 200:
            return response.content  # Returns the image data in PNG format
        else:
            response.raise_for_status()


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

    api = AretasAPIUtils(access_token)

    # Fetch data
    alert_history_record = api.fetch_alert_history_record(alert_history_record_id, access_token)
    alert = api.fetch_alert(alert_history_record.alertId, access_token)

    # Calculate times with padding
    alert_time = datetime.fromtimestamp(alert_history_record.timestamp / 1000)
    rtn_time = datetime.fromtimestamp(
        alert_history_record.rtnTimestamp / 1000) if alert_history_record.rtnTimestamp > 0 else datetime.now()
    start_time = int((alert_time - timedelta(hours=1)).timestamp() * 1000)
    end_time = int((rtn_time + timedelta(hours=1)).timestamp() * 1000)

    # Fetch chart image
    chart_image_bytes = api.fetch_image_plotly(alert_history_record.mac,
                                               start_time,
                                               end_time,
                                               alert_history_record.type,
                                               access_token)

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
    </body>
    </html>
    """

    template = Template(html_template)
    html_content = template.render(
        alert=alert,
        alert_history=alert_history_record,
        alert_time=alert_time_str,
        rtn_time=rtn_time_str,
        chart_image_base64=chart_image_base64
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
