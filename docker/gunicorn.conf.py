import os

bind = "0.0.0.0:8000"

# Requests mostly wait on the database; a waiting thread costs a stack, a
# waiting process costs an interpreter.
worker_class = "gthread"

# Not derived from os.cpu_count(): in a container it reports the host's cores,
# not the container's CPU limit.
workers = int(os.environ.get("GUNICORN_WORKERS", "1"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))

# Recycling bounds slow leaks; jitter stops every worker restarting at once.
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", "100"))

# Workers share the preloaded app copy-on-write instead of importing it each.
preload_app = True

timeout = int(os.environ.get("GUNICORN_TIMEOUT", "30"))
# stop_grace_period in compose.prod.yaml must exceed this or Docker kills the
# drain halfway.
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "20"))
keepalive = int(os.environ.get("GUNICORN_KEEPALIVE", "5"))

# Its default location is under /app, which is read-only.
control_socket_disable = True
# The heartbeat file on disk can stall under I/O load and get workers killed.
worker_tmp_dir = "/dev/shm"

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%({x-forwarded-for}i)s %(t)s "%(r)s" %(s)s %(b)s %(M)sms'

# The proxy arrives via Docker's bridge, not 127.0.0.1. Safe only because
# compose.prod.yaml publishes the port on loopback.
forwarded_allow_ips = "*"
