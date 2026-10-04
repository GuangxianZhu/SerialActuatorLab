/* Generic half-duplex serial bridge teaching example.
 * Implement board.h on your platform; this is not a ready-to-flash image.
 * [01] through [12] synchronize the code view with the animation;
 * Lettered sub-tags (02a, 02b, ...) mark the detailed MCU-internal steps.
 */
#include "board.h"

static uint8_t g_buf[PKT_MAX];   /* Host instruction packet. */
static uint8_t g_rx[PKT_MAX];    /* Actuator status packet. */

static uint32_t read_packet(UART_T *uart, uint8_t *buf,
                            uint32_t timeout_ms)
{
    static const uint8_t HDR[4] = {0xFF, 0xFF, 0xFD, 0x00};
    uint32_t n = 0, need = 7, t0 = millis();
    while (n < need) {
        /* [09][10a] Wait for a reply, subject to the timeout. */
        if (timeout_ms && (millis() - t0) > timeout_ms)
            return 0;
        /* [01][02a][02b][02c] No byte in the receive FIFO: keep waiting.
         * Meanwhile the UART hardware samples bits on its own. */
        if (UART_GET_RX_EMPTY(uart))
            continue;
        /* [02][02d][10] Read one byte from the UART. */
        uint8_t b = (uint8_t)UART_READ(uart);
        /* [02e] Bytes 0-3 must match the header; else resynchronize. */
        if (n < 4 && b != HDR[n]) {
            n = (b == 0xFF) ? ((n == 2) ? 2 : 1) : 0;
            buf[0] = 0xFF;
            continue;
        }
        /* [02][02e][10] Store the byte and advance the count. */
        buf[n++] = b;
        if (n == 7) {
            /* [03][03a] Length (little-endian) sets the packet size. */
            need = 7u + (buf[5] | (buf[6] << 8));
            /* [03b] Reject impossible sizes before overflowing buf. */
            if (need < 10u || need > PKT_MAX) return 0;
        }
    }
    /* [03][03c] A complete packet is available. */
    return n;
}

static void motor_send(const uint8_t *p, uint32_t len)
{
    /* [04a] Discard stale bytes left in the actuator RX FIFO. */
    while (!UART_GET_RX_EMPTY(MOTOR_UART))
        (void)UART_READ(MOTOR_UART);
    /* [04][04b] DIR high: enable TX, disable RX. */
    gpio_write_dir(1);
    for (uint32_t i = 0; i < len; i++) {
        /* [05a] TX FIFO full? Spin until a slot frees up. */
        while (UART_IS_TX_FULL(MOTOR_UART)) {}
        /* [05][05b] Queue one byte; hardware serializes its bits. */
        UART_WRITE(MOTOR_UART, p[i]);
        /* [05c][05d] No code: the UART frames and shifts each byte. */
    }
    /* [06] Wait until the final stop bit has left the pin. */
    while (!uart_tx_complete(MOTOR_UART)) {}
    /* [07] DIR low: TX high impedance, enable RX. */
    gpio_write_dir(0);
}

static void pc_write(const uint8_t *p, uint32_t len)
{
    for (uint32_t i = 0; i < len; i++) {
        /* [11a] Same pattern as motor_send: wait for a free slot. */
        while (UART_IS_TX_FULL(PC_UART)) {}
        /* [11] Forward the original reply byte to the host. */
        UART_WRITE(PC_UART, p[i]);
    }
}

int main(void)
{
    /* [01a] Clocks, baud-rate dividers and GPIO modes, once. */
    board_init();
    gpio_write_dir(0);
    while (1) {
        /* [01][12] Wait for the host's next complete packet. */
        uint32_t len = read_packet(PC_UART, g_buf, WAIT_FOREVER);
        if (len == 0) continue;
        motor_send(g_buf, len);
        /* [08] Wait for the actuator to process and reply. */
        uint32_t n = read_packet(MOTOR_UART, g_rx,
                                 REPLY_TIMEOUT_MS);
        /* [11] Return the original reply; stay silent on timeout. */
        if (n) pc_write(g_rx, n);
    }
}
