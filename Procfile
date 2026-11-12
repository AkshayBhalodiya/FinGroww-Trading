web: gunicorn fingroww_market_server:app --workers 1 --worker-class gthread --threads 4 --worker-tmp-dir /dev/shm --max-requests 25000 --max-requests-jitter 2500 --timeout 120
