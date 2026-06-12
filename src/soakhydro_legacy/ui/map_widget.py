from __future__ import annotations

import json
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Qt, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView


HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>SoakSIM Map</title>
    <style>
      html, body, #map { height: 100%; margin: 0; padding: 0; }
      .leaflet-container { font: inherit; }
    </style>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
  </head>
  <body>
    <div id="map"></div>
    <script>
      let map;
      let marker = null;
      let backend = null;

      function initMap(lat, lng, zoom) {
        map = L.map('map').setView([lat, lng], zoom);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: 19,
          attribution: '&copy; OpenStreetMap contributors'
        }).addTo(map);
        map.on('click', (e) => {
          setMarker(e.latlng.lat, e.latlng.lng);
          if (backend) {
            backend.setCoordinate(e.latlng.lat, e.latlng.lng);
          }
        });
      }

      function setMarker(lat, lng) {
        if (!map) return;
        if (marker) {
          marker.setLatLng([lat, lng]);
        } else {
          marker = L.marker([lat, lng]).addTo(map);
        }
        map.panTo([lat, lng]);
      }

      new QWebChannel(qt.webChannelTransport, function(channel) {
        backend = channel.objects.bridge;
        backend.initialize.connect(function(payload) {
          const data = JSON.parse(payload);
          initMap(data.lat, data.lng, data.zoom);
          if (data.selected) {
            setMarker(data.selected.lat, data.selected.lng);
          }
        });
        backend.updateMarker.connect(function(payload) {
          const data = JSON.parse(payload);
          setMarker(data.lat, data.lng);
        });
        backend.requestInitialState();
      });
    </script>
  </body>
</html>
"""


class MapBridge(QObject):
    initialize = Signal(str)
    updateMarker = Signal(str)
    coordinateChanged = Signal(float, float)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._initial_state: dict[str, object] = {
            "lat": -25.2744,
            "lng": 133.7751,
            "zoom": 4,
            "selected": None,
        }

    @Slot(float, float)
    def setCoordinate(self, latitude: float, longitude: float) -> None:  # noqa: N802
        self._initial_state["selected"] = {"lat": latitude, "lng": longitude}
        self.coordinateChanged.emit(latitude, longitude)

    @Slot()
    def requestInitialState(self) -> None:  # noqa: N802
        self.initialize.emit(json.dumps(self._initial_state))

    def push_marker(self, latitude: float, longitude: float) -> None:
        self._initial_state["selected"] = {"lat": latitude, "lng": longitude}
        self.updateMarker.emit(json.dumps(self._initial_state["selected"]))

    def set_view(self, latitude: float, longitude: float, zoom: int = 4) -> None:
        self._initial_state["lat"] = latitude
        self._initial_state["lng"] = longitude
        self._initial_state["zoom"] = zoom


class MapWidget(QWebEngineView):
    coordinateSelected = Signal(float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.bridge = MapBridge(self)
        channel = QWebChannel(self)
        channel.registerObject("bridge", self.bridge)
        self.page().setWebChannel(channel)
        self.bridge.coordinateChanged.connect(self.coordinateSelected)
        self._load_html()

    def _load_html(self) -> None:
        self.setHtml(HTML_TEMPLATE, baseUrl=QUrl("https://soaksim.local"))

    def set_initial_view(self, latitude: float, longitude: float, zoom: int = 4) -> None:
        self.bridge.set_view(latitude, longitude, zoom)

    def set_marker(self, latitude: float, longitude: float) -> None:
        self.bridge.push_marker(latitude, longitude)
```}