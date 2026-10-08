# Copyright 2026 IQM developers
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
Only a subset of the IQM server REST API V1 is implemented. Namely the
endpoints needed by the CUDA-Q client are implemented here.

This server is configured with the following environment variables:
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
from fastapi import FastAPI, Request, Response
import uvicorn
import httpx


# Define the REST Server App
app = FastAPI(title="IQM API Proxy Server", version="V1")
# One time global configuration
server: str = ""
qc: str = ""
token: str = ""
port: int = 0


# List of HTTP header fields to be dropped in requests and responses.
DROP_FROM_REQ = {"host", "content-length", "connection",
                 "transfer-encoding", "keep-alive", "upgrade"}
DROP_FROM_RSP = {"content-encoding", "content-length", "connection",
                 "transfer-encoding", "keep-alive"}

async def _forward_request(request: Request, path: str) -> Response:
    """Forward the request"""
    # filter and rewrite the header fields
    headers = httpx.Headers(
        [(k, v) for k, v in request.headers.items() if k.lower() not in DROP_FROM_REQ]
    )
    if token:
        headers["authorization"] = f"Bearer {token}"

    body = await request.body()

    if "circuit" in path:
        print(f"*** {path}\n  {body}\n")
        """ *** TODO: this is the place to modify the circuit JSON *** """

    async with httpx.AsyncClient(base_url=server) as client:
        resp = await client.request(
            headers=headers,
            method=request.method,
            url=path,
            content=body,
        )

    # print(f"*** Body ***\n{resp.content}\n")

    response = Response(
        content=resp.content,
        status_code=resp.status_code,
    )
    for k, v in resp.headers.multi_items():
        if k.lower() not in DROP_FROM_RSP:
            response.headers.append(k, v)
    return response


@app.get("/api/v1/calibration-sets/{rqc}/default/dynamic-quantum-architecture")
async def _get_dynamic_quantum_architecture(request: Request) -> Response:
    """Get the dynamic quantum architecture"""
    path = request.url.path
    if (qc):
        path = f"api/v1/calibration-sets/{qc}/default/dynamic-quantum-architecture"
    return await _forward_request(request, path)


@app.post("/api/v1/jobs/{rqc}/circuit")
async def _post_job(request: Request) -> Response:
    """Post a circuit for execution"""
    path = request.url.path
    if (qc):
        path = f"api/v1/jobs/{qc}/circuit"
    return await _forward_request(request, path)


@app.get("/api/v1/jobs/{job_id}")
@app.get("/api/v1/jobs/{job_id}/payload")
@app.get("/api/v1/jobs/{job_id}/artifacts/measurement_counts")
async def _get_transparent(job_id: str, request: Request) -> Response:
    """Get using the path from request"""
    return await _forward_request(request, request.url.path)


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

    print(f"Configured upstream server: '{server}' & quantum computer: '{qc}'")

    uvicorn.run(app, port=port, host='0.0.0.0', log_level="info")


if __name__ == "__main__":
    startProxy()
