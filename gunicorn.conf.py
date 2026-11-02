import os

bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"
workers = 1
worker_class = "gthread"
threads = 4
timeout = 120
worker_tmp_dir = "/dev/shm"
max_requests = 1000
max_requests_jitter = 100
keepalive = 5
