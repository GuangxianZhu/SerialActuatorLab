/* Platform-neutral hardware adaptation interface for the teaching example.
 * Implement these functions for your own board before using real hardware.
 * No processor-specific drivers or register addresses are included.
 */
#ifndef BOARD_H
#define BOARD_H
#include <stdint.h>

typedef struct SerialPort UART_T;
extern UART_T *PC_UART;
extern UART_T *MOTOR_UART;
void board_init(void);
uint32_t millis(void);
uint32_t UART_GET_RX_EMPTY(UART_T *uart);
uint32_t UART_READ(UART_T *uart);
uint32_t UART_IS_TX_FULL(UART_T *uart);
void UART_WRITE(UART_T *uart, uint8_t byte);
/* True only when FIFO AND shift register are empty, including the stop bit. */
uint32_t uart_tx_complete(UART_T *uart);
void gpio_write_dir(uint32_t level);

#define PKT_MAX 64u
#define WAIT_FOREVER 0u
#define REPLY_TIMEOUT_MS 20u
#endif
