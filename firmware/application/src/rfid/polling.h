#ifndef POLLING_H
#define POLLING_H

#include <stdbool.h>
#include <stdint.h>

// Fixed-delay slot polling: periodically switch to the next enabled slot.
void polling_init(void);
void polling_start(void);   // (re)start the polling timer per settings
void polling_stop(void);
void polling_process(void); // call from main loop
bool polling_is_running(void);

#endif
