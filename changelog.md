Changes
## Bluetooth mode
* Option to toggle between usb and bluetooth mode during startup [1]
* Option to specify specific BT address with --btport
* Option to specify specific USB address with --usbport
* Old option --port deprecated (use --usbport instead)
#### Notes
* [1] Option is available after 5 seconds without a successful connection, and only if no --btport or --usbport arguments were passed in
* Most recent connection settings are saved automatically
* Lichess.org is not enabled in bluetooth mode at the moment

## Remote control
* Remote control is automatically enabled when switching to bluetooth mode and disabled when switching to usb mode
* Option to manually enable or disable remote control in options menu (chessboard settings)
* Old option --picochess to specify remote control deprecated (use settings window instead)
