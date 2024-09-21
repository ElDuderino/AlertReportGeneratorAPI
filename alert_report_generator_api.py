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

import os

os.add_dll_directory(r"C:\msys64\mingw64\bin\\")

app = FastAPI()


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
    alertId: str
    name: str
    sensorType: int
    threshold: float
    duration: int


def fetch_alert_history_record(alert_history_record_id: int, authorization: str) -> AlertHistoryRecord:
    url = f"http://internal.rest.api/alertHistory/{alert_history_record_id}"
    headers = {'Authorization': authorization}
    # For now, we'll use a stubbed response
    return AlertHistoryRecord(
        mac=123456789,
        timestamp=1633046400000,
        type=1,
        data=75.5,
        alertId="alert123",
        isActive=False,
        eventId=alert_history_record_id,
        rtnTimestamp=1633050000000
    )


def fetch_alert(alertId: str, authorization: str) -> Alert:
    url = f"http://internal.rest.api/alerts/{alertId}"
    headers = {'Authorization': authorization}
    # Stubbed response
    return Alert(
        alertId=alertId,
        name="High Temperature Alert",
        sensorType=1,
        threshold=70.0,
        duration=300
    )


def fetch_chart_image(mac: int, start_time: int, end_time: int, sensor_type: int, authorization: str) -> bytes:
    url = f"http://internal.rest.api/chart?mac={mac}&start={start_time}&end={end_time}&type={sensor_type}"
    headers = {'Authorization': authorization}
    # Stubbed response: Generate a placeholder image
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise ImportError("Please install Pillow: pip install Pillow")
    img = Image.new('RGB', (600, 400), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    text = "Sensor Data Chart Placeholder"
    font_size = 20
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except IOError:
        font = ImageFont.load_default()
    text_width, text_height = d.textsize(text, font=font)
    x = (img.width - text_width) / 2
    y = (img.height - text_height) / 2
    d.text((x, y), text, fill=(0, 0, 0), font=font)
    buffer = BytesIO()
    img.save(buffer, format='JPEG')
    return buffer.getvalue()


@app.get("/generate_alert_pdf/{alert_history_record_id}")
async def generate_alert_pdf(alert_history_record_id: int, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")

    # Fetch data
    alert_history_record = fetch_alert_history_record(alert_history_record_id, authorization)
    alert = fetch_alert(alert_history_record.alertId, authorization)

    # Calculate times with padding
    alert_time = datetime.fromtimestamp(alert_history_record.timestamp / 1000)
    rtn_time = datetime.fromtimestamp(
        alert_history_record.rtnTimestamp / 1000) if alert_history_record.rtnTimestamp > 0 else datetime.now()
    start_time = int((alert_time - timedelta(hours=1)).timestamp() * 1000)
    end_time = int((rtn_time + timedelta(hours=1)).timestamp() * 1000)

    # Fetch chart image
    chart_image_bytes = fetch_chart_image(alert_history_record.mac, start_time, end_time, alert_history_record.type,
                                          authorization)
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
            <p><strong>Alert ID:</strong> {{ alert.alertId }}</p>
            <p><strong>Alert Name:</strong> {{ alert.name }}</p>
            <p><strong>Sensor Type:</strong> {{ alert.sensorType }}</p>
            <p><strong>Threshold:</strong> {{ alert.threshold }}</p>
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
            <img src="data:image/jpeg;base64,{{ chart_image_base64 }}" alt="Sensor Data Chart" />
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
    pdf = weasyprint.HTML(string=html_content).write_pdf()

    return StreamingResponse(BytesIO(pdf), media_type="application/pdf",
                             headers={"Content-Disposition": "inline; filename=alert_report.pdf"})


if __name__ == "__main__":
    import uvicorn

    # Only run if this file is executed directly
    uvicorn.run(app, host="0.0.0.0", port=8100, log_level="info")
