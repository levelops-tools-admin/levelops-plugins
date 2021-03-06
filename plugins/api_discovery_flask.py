#!/usr/bin/env python

##################################################################
#  Copyright (C) 2019-2020 LevelOps Inc <support@levelops.io>
#  
#  This file is part of the LevelOps Inc Tools.
#  
#  This tool is licensed under Apache License, Version 2.0
##################################################################

import logging
import sys
import re
import os
import inspect
import time
currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
sys.path.insert(0,parentdir) 

from ujson import dump, dumps
from argparse import ArgumentParser
from sdk.types import Endpoint, API, Report
from sdk.fs_processor import Scanner
from sdk.plugins import Runner, Plugin, labels_parser, default_plugin_options


log = logging.getLogger(__name__)
plugin = Plugin(name="sast_api_flask", version="1")


def process_file(f_path):
  # parse file contents and collect APIs
  # detect single line annotations
  # detect multi line annotations
  """
    @app.route('/user/<username>')
    @app.route( '/user/<username>')
    @app.route ( '/user/<username>')
    @app. route ( '/user/<username>')
    @app .route ( '/user/<username>')
    @app . route ( '/user/<username>' )
    @app.route('/post/<int:post_id>')
    @app.route('/path/<path:subpath>')
    @app.route('/')
    @app.route('/login', methods=['GET', 'POST'])
    @app.route(methods=['GET', 'POST'], rule='/login')
    @application.route(methods=['GET', 'POST'], rule='/login')
  """
  log.debug("path: %s" % f_path)
  api_found = False
  inside_class = False
  prefix = ""
  api = API(name=f_path)
  pattern = re.compile(pattern='^\s*(@(\w*\s*\.\s*route)\s*\(\s*(.*\,\s*)*(rule\s*=\s*)?[\"\']([\w\/\{\}\w\:\w\s\[\]\+\.\*\\\<\>\-]+)[\"\'](\s*,.*)*\s*\)).*$', flags=(re.I | re.M))
  # class_pattern = re.compile(pattern='^\s*public\s*class\s*.+$', flags=(re.I | re.M))
  with open(f_path) as file:
    line = file.readline()
    while line:
      result = pattern.match(line)
      if result:
        api_found = True
        log.debug("API!! %s, %s", f_path, result.group(5))
        api.add_endpoint( Endpoint( path=(prefix+result.group(5)).replace('//', '/') ))
      line = file.readline()
  # if there was only the root mapping we add it as a single endpoint
  if prefix != "" and not api_found:
    api.add_endpoint( Endpoint(path=prefix))
    api_found = True
  if api_found:
    return api


def validate_args(options, f_targets):
  if options.debug:
      log.setLevel('DEBUG')
  if options.submit:
    if not options.product or not options.token:
      log.error("Both product and token options are required if the submit flag is present.")
      sys.exit(1)
  if options.json and options.csv:
      log.error("Only one output format can be selected at one time. Either pass the flag --json or --csv or no flag for standard output.")
      sys.exit(1)
  if (options.json or options.csv) and not options.output_file and not options.print_results:
      log.error("To use --csv or --json, either the --print-results flag (to print to the console) or the --out flag (to write to a file) must be specified.")
      sys.exit(1)

  if len(f_targets) < 1:
    log.error("must provide a list of directories to scan (space separated)")
    sys.exit(1)


def get_options():
  parser = ArgumentParser(prog="Levelops flask configuration scanner.", usage="./api_discovery_flask.py (optional <flags>) <directory to scan>")
  parser.add_argument('-t', '--threads', dest='threads', help='Number of threads', type=int, default=5)
  for parser_option in default_plugin_options:
    parser.add_argument(*parser_option['args'], **parser_option['kwords'])
  
  return parser.parse_known_args()


def handle_output(options, results):
    if options.json:
      if options.print_results:
        log.info(dumps(results, indent=2, escape_forward_slashes=False))
      if options.output_file:
        with open(options.output_file, 'w') as f:
          dump(results, f, indent=2, escape_forward_slashes=False)

    elif options.csv:
      if options.print_results:
        log.info("reference, api_endpoint")
        for api in results.apis:
          for endpoint in api.endpoints:
            log.info("%s,%s", api.name, endpoint.path)
      if options.output_file:
        with open(options.output_file, 'w') as f:
          f.write("reference, api_endpoint\n")
          for api in results.apis:
            for endpoint in api.endpoints:
              f.write("%s,%s\n" % (api.name, endpoint.path))

    elif options.print_results or options.output_file:
      if options.output_file:
        with open(options.output_file, 'w') as f:
          for api in results.apis:
            for endpoint in api.endpoints:
              f.write("%s     %s\n" % (api.name, endpoint.path))
      if options.print_results:
        log.info("======================================")
        log.info("Report:")
        # log.info("%s", report)
        for api in results.apis:
          for endpoint in api.endpoints:
            log.info("%s     %s", api.name, endpoint.path)


if __name__ == "__main__":
  logging.basicConfig(level="INFO", format="[%(threadName)s] [%(levelname)s]: %(message)s")

  options, f_targets = get_options()
  validate_args(options, f_targets)

  runner = Runner(base_url=options.endpoint)
  success = False
  start_time = time.time()
  try:
    s = Scanner(queue_timeout=0.5)
    for f_target in f_targets:
      log.info("scanning path: %s" % f_target)
      s.scan_directory(base_path=f_target, filters=".py", action=process_file)
    s.wait_and_finish()
    success = True
    results =  s.get_report()

    handle_output(options, results)
  except Exception as e:
    log.error("Couldn't successfully complete the scanning.", e, exc_info=True)
    results = str(e)
  except:
    error = sys.exc_info()
    log.error("Couldn't successfully complete the scanning: %s - %s", error[0], error[1], error[2])
    results = str(e)
  finally:
    end_time = time.time()
    if options.submit:
      # post failure to levelops
      runner.submit(success=success, results=results, product_id=options.product, token=options.token, plugin=plugin, elapsed_time=(end_time - start_time), labels=options.labels, tags=options.tags)
  if success:
    sys.exit(0)
  else:
    sys.exit(1)