# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.13.6

FROM python:${PYTHON_VERSION}-slim

LABEL fly_launch_runtime="flask"

RUN apt-get update && apt-get install -y graphviz

WORKDIR /code

COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]
