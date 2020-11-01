xonsh2
------

The `xonsh2 <https://github.com/anki-code/xonsh2>`_ repository was built by `my-xonsh-fork <https://github.com/anki-code/my-xonsh-fork>`_
from `xonsh-xep-2 <https://github.com/anki-code/xonsh-xep-2>`_ repository that has `XEP-2 <https://github.com/anki-code/xonsh-operators-proposal/blob/main/XEP-2.rst>`_ changes. 

The installation of ``xonsh2`` will not affect your host xonsh installation. You can install xonsh2 and: run it, create ``.xonshrc_2``, add to
the shebang (``#!/usr/bin/env xonsh2``), run scripts (``xonsh2 my.xsh``), put xontribs to ``xontrib2`` directory
and load it via ``xontrib2 load``. Original xonsh will live shoulder to shoulder with xonsh2 in fact.

Install and try:

.. code-block:: bash

    pip install -U git+https://github.com/anki-code/xonsh2
    xonsh2

Feel free to make pull requests or create issues in the `xonsh-xep-2 <https://github.com/anki-code/xonsh-xep-2>`_
repository if you like the XEP-2 approach.
