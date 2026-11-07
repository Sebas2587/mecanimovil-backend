#!/bin/bash
# Helper script to run Django with correct GDAL/GEOS paths
export GDAL_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/libgdal.so.34
export GEOS_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/libgeos_c.so
export PYTHONPATH=/agent/repos/mecanimovil-backend:$PYTHONPATH

cd /agent/repos/mecanimovil-backend
exec /agent/repos/mecanimovil-backend/venv/bin/python "$@"
