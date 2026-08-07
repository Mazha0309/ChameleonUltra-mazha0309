#ifndef POLLING_H
#define POLLING_H

#include <stdbool.h>
#include <stdint.h>

// Field-triggered slot polling: while a reader field is present, cycle through
// the enabled slots at the configured interval; when the reader leaves, restore
// the original slot. Idle (no reader) = no switching.
void polling_init(void);
void polling_start(void);   // (re)start the polling timer per settings
void polling_stop(void);
void polling_process(void); // call from main loop
bool polling_is_running(void);
// Called by the HF tag module on every frame received from the reader.
void polling_note_reader_activity(void);

#endif
