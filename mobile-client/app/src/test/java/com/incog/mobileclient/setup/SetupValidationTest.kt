package com.incog.mobileclient.setup

import com.incog.mobileclient.config.Contact
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class SetupValidationTest {

    private fun c(phone: String, name: String = "") = Contact(name, phone)

    @Test
    fun `one valid contact and distinct codes pass`() {
        assertNull(validate(listOf(c("+919876543210")), "271828", "314159", "191919"))
    }

    @Test
    fun `multiple valid contacts pass`() {
        assertNull(
            validate(
                listOf(c("+919876543210", "A"), c("9998887777", "B")),
                "271828", "314159", "191919"
            )
        )
    }

    @Test
    fun `no contact with a phone is rejected`() {
        assertNotNull(validate(emptyList(), "271828", "314159", "191919"))
        assertNotNull(validate(listOf(c("", "NameOnly")), "271828", "314159", "191919"))
    }

    @Test
    fun `an invalid phone among the contacts is rejected`() {
        assertNotNull(validate(listOf(c("+919876543210"), c("call-me")), "271828", "314159", "191919"))
        assertNotNull(validate(listOf(c("12345")), "271828", "314159", "191919"))
    }

    @Test
    fun `code shorter than four digits is rejected`() {
        assertNotNull(validate(listOf(c("+919876543210")), "123", "314159", "191919"))
    }

    @Test
    fun `code with a leading zero is rejected`() {
        assertNotNull(validate(listOf(c("+919876543210")), "012345", "314159", "191919"))
    }

    @Test
    fun `duplicate codes are rejected`() {
        assertNotNull(validate(listOf(c("+919876543210")), "271828", "271828", "191919"))
    }
}
