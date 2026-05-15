Traceback (most recent call last):
  File "/snap/snapcraft/17634/bin/snapcraft", line 12, in <module>
    sys.exit(main())
             ^^^^^^
  File "/snap/snapcraft/17634/lib/python3.12/site-packages/snapcraft/application.py", line 475, in main
    return cli.run()
           ^^^^^^^^^
  File "/snap/snapcraft/17634/lib/python3.12/site-packages/snapcraft/cli.py", line 259, in run
    _run_dispatcher(dispatcher, global_args)
  File "/snap/snapcraft/17634/lib/python3.12/site-packages/snapcraft/cli.py", line 232, in _run_dispatcher
    dispatcher.run()
  File "/snap/snapcraft/17634/lib/python3.12/site-packages/craft_cli/dispatcher.py", line 564, in run
    return self._loaded_command.run(self._parsed_command_args)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/snap/snapcraft/17634/lib/python3.12/site-packages/snapcraft/commands/core22/lifecycle.py", line 268, in run
    super().run(parsed_args)
  File "/snap/snapcraft/17634/lib/python3.12/site-packages/snapcraft/commands/core22/lifecycle.py", line 141, in run
    parts_lifecycle.run(self.name, parsed_args)
  File "/snap/snapcraft/17634/lib/python3.12/site-packages/snapcraft/parts/lifecycle.py", line 89, in run
    partitions = _validate_and_get_partitions(yaml_data)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/snap/snapcraft/17634/lib/python3.12/site-packages/snapcraft/parts/lifecycle.py", line 819, in _validate_and_get_partitions
    project = models.ComponentProject.unmarshal(yaml_data)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/snap/snapcraft/17634/lib/python3.12/site-packages/craft_application/models/base.py", line 64, in unmarshal
    return cls.model_validate(data)
           ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/snap/snapcraft/17634/lib/python3.12/site-packages/pydantic/main.py", line 716, in model_validate
    return cls.__pydantic_validator__.validate_python(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
pydantic_core._pydantic_core.ValidationError: 2 validation errors for ComponentProject
components.model-faster-rcnn.summary
  Field required [type=missing, input_value={'type': 'standard', 'des... auto-configuration.\n'}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.12/v/missing
components.model-efficientnet.summary
  Field required [type=missing, input_value={'type': 'standard', 'des... auto-configuration.\n'}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.12/v/missing
