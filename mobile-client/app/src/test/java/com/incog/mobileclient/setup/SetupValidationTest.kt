package com.incog.mobileclient.setup

import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class SetupValidationTest {

    @Test
    fun `valid contact and distinct codes pass`() {
        assertNull(validate("+919876543210", "271828", "314159", "191919"))
    }

    @Test
    fun `plain digits phone without plus is accepted`() {
        assertNull(validate("9876543210", "271828", "314159", "191919"))
    }

    @Test
    fun `too-short phone is rejected`() {
        assertNotNull(validate("12345", "271828", "314159", "191919"))
    }

    @Test
    fun `non-numeric phone is rejected`() {
        assertNotNull(validate("call-me", "271828", "314159", "191919"))
    }

    @Test
    fun `code shorter than four digits is rejected`() {
        assertNotNull(validate("+919876543210", "123", "314159", "191919"))
    }

    @Test
    fun `code with a leading zero is rejected`() {
        assertNotNull(validate("+919876543210", "012345", "314159", "191919"))
    }

    @Test
    fun `duplicate codes are rejected`() {
        assertNotNull(validate("+919876543210", "271828", "271828", "191919"))
    }
}
