# Copyright 2026 IQM Quantum Computers
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Proxy server for the IQM REST API.

Forward requests sent to this server to the configured upstream server.
Note: This has not been tested beyond the API endpoints needed by CUDA-Q.

This proxy server is configured with the following environment variables:
- 'IQM_SERVER_URL': string containing the URL of the upstream server.
  This string must not be empty. If empty the proxy will not start.
- 'IQM_QUANTUM_COMPUTER': string containing the name of the quantum computer
  to use on the upstream server. If not set the quantum computer given in the
  request from the client is used.
- 'IQM_TOKEN': string containing any API token required by the upstream server.
  If not set the authentication token in the request from the client
  is used.
- 'IQM_PROXY_PORT': Port number on which the proxy is listening. If not set
  the port number 60000 is used.

Once the proxy starts it prints the URL on which it is listening.
The CUDA-Q program should then be configured to use this URL by setting the
environment variable 'IQM_SERVER_URL' in the shell in which it is executed.
"""

from os import getenv
from sys import exit
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, HTTPException
import uvicorn
import httpx
import logging

# One time global configuration
server: str = ""
qc: str = ""
token: str = ""
port: int = 0

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Configured upstream server: '{server}'")
    logger.info(f"Configured quantum computer: '{qc}'")
    app.state.client = httpx.AsyncClient(
        base_url=server,
        timeout=httpx.Timeout(20, connect=10),
        limits=httpx.Limits(max_keepalive_connections=20, keepalive_expiry=30),
        transport=httpx.AsyncHTTPTransport(retries=2),
    )
    yield
    await app.state.client.aclose()


# The REST Server App
app = FastAPI(title="IQM API Proxy Server", version="V1", lifespan=lifespan)

# List of HTTP header fields to be dropped in requests and responses.
DROP_FROM_REQ = {
    "host", "content-length", "connection", "te", "trailers",
    "transfer-encoding", "keep-alive", "upgrade", "proxy-authenticate",
    "proxy-authorization"
}
DROP_FROM_RSP = {
    "content-encoding", "content-length", "connection", "transfer-encoding",
    "keep-alive"
}


async def _forward_request(request: Request, path: str) -> Response:
    """Forward the request"""
    client: httpx.AsyncClient = request.app.state.client

    # filter and rewrite the header fields
    headers = httpx.Headers([(k, v)
                             for k, v in request.headers.items()
                             if k.lower() not in DROP_FROM_REQ])
    if token:
        headers["authorization"] = f"Bearer {token}"

    body = await request.body()

    if request.method == "POST" and "circuit" in path:
        print(f"*** {path}\n  {body}\n")
        """ *** TODO: this is the place to modify the circuit JSON *** """

    try:
        logger.info(f"Forwarding: {request.method} '{path}'")
        resp = await client.request(
            headers=headers,
            method=request.method,
            url=path,
            content=body,
        )
    except httpx.ConnectTimeout:
        raise HTTPException(504, "Timeout connecting to upstream server")
    except httpx.ReadTimeout:
        raise HTTPException(504, "Timeout reading from upstream server")
    except httpx.ConnectError:
        raise HTTPException(504, "Failed to connect to upstream server")

    # print(f"*** Body ***\n{resp.content}\n")

    response = Response(
        content=resp.content,
        status_code=resp.status_code,
    )
    for k, v in resp.headers.multi_items():
        if k.lower() not in DROP_FROM_RSP:
            response.headers.append(k, v)
    return response


# initial API
@app.post("/circuits")
@app.get("/circuits/{job_id}/status")
@app.get("/circuits/{job_id}/counts")
@app.get("/calibration-sets/default/dynamic-quantum-architecture")
# V1 API
@app.get("/api/v1/quantum-computers")
@app.post("/api/v1/jobs/{job_id}/cancel")
@app.delete("/api/v1/jobs/{job_id}")
@app.get("/api/v1/jobs/{job_id}")
@app.get("/api/v1/jobs/{job_id}/payload")
@app.get("/api/v1/jobs/{job_id}/artifacts/{artifact_type}")
@app.post("/api/v1/iterations")
@app.post("/api/v1/iterations/{iteration_id}/end")
@app.get("/api/v1/iterations")
@app.get("/api/v1/iterations/{iteration_id}")
@app.get("/api/v1/iterations/{iteration_id}/jobs")
@app.post("/api/v1/tokens/{id}/revoke")
@app.post("/api/v1/tokens/current/activate")
@app.post("/api/v1/tokens/current/refresh")
@app.get("/api/v1/tokens")
async def _get_transparent(request: Request) -> Response:
    """Get using the path from request"""
    return await _forward_request(request, request.url.path)


# V1 API (with qc)
@app.post("/api/v1/quantum-computers/{rqc}/timeslots")
@app.delete("/api/v1/quantum-computers/{rqc}/timeslots")
@app.get("/api/v1/quantum-computers/{rqc}")
@app.get("/api/v1/quantum-computers/{rqc}/artifacts/{artifact_type}")
@app.get("/api/v1/quantum-computers/{rqc}/health")
@app.get("/api/v1/quantum-computers/{rqc}/limits")
@app.get("/api/v1/quantum-computers/{rqc}/queue-availability")
@app.get("/api/v1/quantum-computers/{rqc}/timeslots")
@app.post("/api/v1/jobs/{rqc}/{job_type}")
@app.get("/api/v1/calibration-sets/{rqc}/{cal_set}")
@app.get("/api/v1/calibration-sets/{rqc}/{cal_set}/dynamic-quantum-architecture")
@app.get("/api/v1/calibration-sets/{rqc}/{cal_set}/metrics")
async def _get_dynamic_quantum_architecture(request: Request) -> Response:
    """Forward the incoming request but first rewrite the path if a quantum
       computer is configured."""
    path = request.url.path
    # In V1 API the quantum computer is always the 4th level of a path
    if (qc):
        parts = path.split("/")
        if len(parts) >= 5:
            parts[4] = qc
        path = "/".join(parts)
    return await _forward_request(request, path)


def startProxy():
    global server
    global qc
    global token
    global port
    server = getenv("IQM_SERVER_URL", "")
    qc = getenv("IQM_QUANTUM_COMPUTER", "")
    token = getenv("IQM_TOKEN", "")
    port = int(getenv("IQM_PROXY_PORT", "60000"))

    if not server:
        exit(f"Error: Server not configured - Aborting")

    uvicorn.run(app, port=port, host='0.0.0.0', log_level="info")


if __name__ == "__main__":
    startProxy()
