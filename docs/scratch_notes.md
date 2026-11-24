# cyberdeck operations findings

i've got a few gripes to document with my cyberdeck.

1. I don't like that inhibit requires mode USB to be selected. this gets in the way of wspr and auto tuner function fairly often.  it was a good idea when the cyberdeck was only a digimodes function, but not now. I'd like ctrl B to toggle inhibit on and off regardless of mode.  I'd instead like ctrl T on the digimodes function to warn that USB mode is not set and block a ctr T until the mode is set correctly.  Also, when the user selects a band from the f1 menu on the digimodes function, it should put the radio in the correct mode when the band is switched to.

2. I'd like "Band" to be menu item 1 on the digimodes function f1 menu. Band, Tune Settings, Mode, Memories.

3. the auto tuner function should work regrardless of the mode the radio is set to because the radio's tune command puts the radio into the right mode and power for tuning.  It already does but due to 1 i have to put the radio into USB before toggling inhibit off in order to run the auto tuner.  If 1 is addressed that should address this item as well.

4. I'd like some work on the wspr mode to check what mode each band set is on and let the user know if they need to be set to USB before running WSPR.  This check should run first thing when the user turns WSPR on from the F1 menu on the WSPR function screen.

5. on the rig screen f1 menu, i'd like an option to set all HF bands to their relevant SSB or all HF bands to Data-U

6. on the rig screen f1 menu, SYSTEM, I don't think clear the transcript should be an item. "nor do I think quit should be an item. when I selected quit it looked like it glitched the cyberdeck.  The clear transcript item only makes sense for the digimodes function and doesn't belong there. i think this is a vestigal apendege carried over from when the deck was only a digimodes funciton.  Each function should have a f1 menu item that fully describes the hotkeys for that function as the last menu item for the f1 screen for that function.

7, when the carrier is moved manually on the digimodes screen (on f2 tune left and right, or on the transcript screen ctrl a ctrl d) i'd like it to snap to even multiples of 5. The carrier may be allowed to move by singleton hz when doing a search or when auto adjusting to the incoming signal.  the current behavior appears to be that it moves in increments of 10 Hz manually but it doesn't re-snap to even multiples if it's already been adjusted by singlton hz by some other process.

8. on the logger, when I switch using the arrow keys to sent or rcvd and hit backspace, it doesn't immediately backspace the characters pre-loaded there. also when I highlight the field, if i start typing "57" or something over it i'd like to just overwrite what is there so I don't have to backspace to overwrite the default 59.  this part of the UI needs to work more smoothly.

9. when I do general logging I just use the master log, and when I re-export it and re-upload it to QRZ it seems to know what to do about the duplicates (historical qsos that i had exported and uploaded before). I'm inclined to keep up with this particular habit/workflow. is there any reason why doing a session by session log and exporting the session rather than the master would be better?  this is for like when I just turn the radio on and pick up a couple of qsos or pota people (me as hunter) where I don't really want to set up a new logger activity, just capture what i hear quickly and upload to qrz at my convenience.