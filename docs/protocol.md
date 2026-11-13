# Serial protocol notes

Summary of the RS-7 ASCII command API (user manual, section 4) as used by this library.

- FTDI USB-serial, **460800 baud** (optionally 115200), 8 data bits, no parity, 1 stop bit.
- Commands are three-letter, case-insensitive, arguments space- or comma-separated, ended by `<CR>`.
- Characters are not echoed.
- Every reply starts with `<CR><LF>`, then one of:
    - `Ok<CR><LF>` for a command without data;
    - one data line, e.g. `0.3834,0.4151<CR><LF>`;
    - a list of lines followed by an empty line (`<CR><LF>`);
    - an error `?nn - explanation<CR><LF>`, or an alarm `?A1 - ...`.
- Whether a reply is a single line or a list depends on the command, so `RS7.command()` takes
  `multiline=True` for list commands (`SCP 0`, `LIN`, `PRE *`, `OSP`, `TSP`).
- Commands that change the output (`SCP`, `OUT`, `PRE`, `FTS`, ...) only answer once the output has
  settled (see `STP`), which can take seconds; hence the 10 s per-line timeout.
- Opening the port can leave a stray character in the unit's input buffer, making the first command fail
  with `?03 - unrecognized command`. `RS7()` sends a bare `<CR>` after opening to flush it.

Observed on a unit with firmware 1.09:

- `USN` answers `Not yet implemented.`
- `LIN` can report `nan` for a channel's wavelength; such values are read as 0.
