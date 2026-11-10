"""Standard mode task modules.
These files are verbatim copies of the desktop ``DP Auto API/complex_modules/*.py``, with only
``from utils.ext_parser import ...`` changed to this project's ``...ext_parser``. Each module exports ``run_xxx_task(log_func, shared_data) -> bool``.
* ``log_func(message)``      Write one log line to the run event stream;
* ``shared_data``            Parameter dict containing ``rest_client`` / ``append_user_record``
                             / ``set_customer_id`` / ``custom_api_payloads`` etc."""
