#!/bin/bash
gunicorn relatorio_generator:app -b 0.0.0.0:10000