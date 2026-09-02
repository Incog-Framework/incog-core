package com.incog.mobileclient.calculator

import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

class CalculatorViewModelTest {

    private lateinit var viewModel: CalculatorViewModel

    @Before
    fun setUp() {
        viewModel = CalculatorViewModel()
    }

    private fun press(vararg actions: CalculatorAction) {
        actions.forEach(viewModel::onAction)
    }

    @Test
    fun `entering digits builds number1`() {
        press(CalculatorAction.Number(1), CalculatorAction.Number(2), CalculatorAction.Number(3))
        assertEquals("123", viewModel.state.value.number1)
    }

    @Test
    fun `leading zero is replaced not appended`() {
        press(CalculatorAction.Number(0), CalculatorAction.Number(5))
        assertEquals("5", viewModel.state.value.number1)
    }

    @Test
    fun `addition computes correct result`() {
        press(
            CalculatorAction.Number(2),
            CalculatorAction.Operation(CalculatorOperation.Add),
            CalculatorAction.Number(3),
            CalculatorAction.Calculate
        )
        assertEquals("5", viewModel.state.value.number1)
        assertEquals("", viewModel.state.value.number2)
        assertEquals(null, viewModel.state.value.operation)
    }

    @Test
    fun `subtraction with decimals computes correct result`() {
        press(
            CalculatorAction.Number(5),
            CalculatorAction.Decimal,
            CalculatorAction.Number(5),
            CalculatorAction.Operation(CalculatorOperation.Subtract),
            CalculatorAction.Number(2),
            CalculatorAction.Calculate
        )
        assertEquals("3.5", viewModel.state.value.number1)
    }

    @Test
    fun `division by zero returns Error`() {
        press(
            CalculatorAction.Number(9),
            CalculatorAction.Operation(CalculatorOperation.Divide),
            CalculatorAction.Number(0),
            CalculatorAction.Calculate
        )
        assertEquals("Error", viewModel.state.value.number1)
    }

    @Test
    fun `chained operations compute intermediate result`() {
        press(
            CalculatorAction.Number(2),
            CalculatorAction.Operation(CalculatorOperation.Add),
            CalculatorAction.Number(3),
            CalculatorAction.Operation(CalculatorOperation.Multiply)
        )
        assertEquals("5", viewModel.state.value.number1)
        assertEquals(CalculatorOperation.Multiply, viewModel.state.value.operation)
    }

    @Test
    fun `clear resets state`() {
        press(
            CalculatorAction.Number(9),
            CalculatorAction.Operation(CalculatorOperation.Add),
            CalculatorAction.Clear
        )
        assertEquals(CalculatorState(), viewModel.state.value)
    }

    @Test
    fun `delete removes last character of active number`() {
        press(CalculatorAction.Number(1), CalculatorAction.Number(2), CalculatorAction.Delete)
        assertEquals("1", viewModel.state.value.number1)
    }

    @Test
    fun `percent converts number to hundredth`() {
        press(CalculatorAction.Number(5), CalculatorAction.Number(0), CalculatorAction.Percent)
        assertEquals("0.5", viewModel.state.value.number1)
    }

    @Test
    fun `toggle sign negates number`() {
        press(CalculatorAction.Number(7), CalculatorAction.ToggleSign)
        assertEquals("-7", viewModel.state.value.number1)
    }
}
