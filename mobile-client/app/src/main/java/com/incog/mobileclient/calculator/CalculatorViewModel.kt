package com.incog.mobileclient.calculator

import androidx.lifecycle.ViewModel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import java.math.BigDecimal
import java.math.RoundingMode

private const val MAX_DIGITS = 12

/**
 * Concealed unlock code. Typing this on the calculator then pressing "=" opens the system
 * Accessibility settings so the owner can enable the Sentinel Engine (an app cannot enable its
 * own accessibility service). Normally typing a lone number and pressing "=" does nothing, so
 * this is invisible during ordinary use. CHANGE THIS to a value only the owner knows.
 */
private const val SECRET_UNLOCK_CODE = "271828"

/**
 * Concealed stand-down code. Typing this then "=" stops an active Ghost State session (e.g. to
 * cancel a false trigger) and returns to Phase 0. Like the unlock code, a lone number + "=" is
 * normally a no-op, so this stays invisible. CHANGE THIS to a value only the owner knows.
 */
private const val STAND_DOWN_CODE = "314159"

/** One-shot UI events the calculator screen must act on (needs an Activity context). */
sealed interface CalculatorEvent {
    data object OpenAccessibilitySettings : CalculatorEvent
    data object StopGhostState : CalculatorEvent
}

class CalculatorViewModel : ViewModel() {

    private val _state = MutableStateFlow(CalculatorState())
    val state: StateFlow<CalculatorState> = _state.asStateFlow()

    private val _events = MutableSharedFlow<CalculatorEvent>(extraBufferCapacity = 1)
    val events: SharedFlow<CalculatorEvent> = _events.asSharedFlow()

    fun onAction(action: CalculatorAction) {
        when (action) {
            is CalculatorAction.Number -> enterNumber(action.digit)
            is CalculatorAction.Decimal -> enterDecimal()
            is CalculatorAction.Clear -> _state.value = CalculatorState()
            is CalculatorAction.Delete -> delete()
            is CalculatorAction.ToggleSign -> toggleSign()
            is CalculatorAction.Percent -> applyPercent()
            is CalculatorAction.Operation -> enterOperation(action.operation)
            is CalculatorAction.Calculate -> calculate()
        }
    }

    private fun enterNumber(digit: Int) {
        _state.update { current ->
            if (current.operation == null) {
                val newNumber1 = when {
                    current.number1 == "0" -> digit.toString()
                    current.number1.length >= MAX_DIGITS -> return@update current
                    else -> current.number1 + digit
                }
                current.copy(number1 = newNumber1)
            } else {
                val newNumber2 = when {
                    current.number2 == "0" -> digit.toString()
                    current.number2.length >= MAX_DIGITS -> return@update current
                    else -> current.number2 + digit
                }
                current.copy(number2 = newNumber2)
            }
        }
    }

    private fun enterDecimal() {
        _state.update { current ->
            if (current.operation == null) {
                if (current.number1.contains(".")) return@update current
                current.copy(number1 = if (current.number1.isEmpty()) "0." else current.number1 + ".")
            } else {
                if (current.number2.contains(".")) return@update current
                current.copy(number2 = if (current.number2.isEmpty()) "0." else current.number2 + ".")
            }
        }
    }

    private fun delete() {
        _state.update { current ->
            when {
                current.number2.isNotEmpty() -> current.copy(number2 = current.number2.dropLast(1))
                current.operation != null -> current.copy(operation = null)
                current.number1.isNotEmpty() -> current.copy(number1 = current.number1.dropLast(1))
                else -> current
            }
        }
    }

    private fun toggleSign() {
        _state.update { current ->
            if (current.operation == null) {
                if (current.number1.isEmpty()) return@update current
                current.copy(number1 = toggle(current.number1))
            } else {
                if (current.number2.isEmpty()) return@update current
                current.copy(number2 = toggle(current.number2))
            }
        }
    }

    private fun toggle(value: String): String =
        if (value.startsWith("-")) value.removePrefix("-") else "-$value"

    private fun applyPercent() {
        _state.update { current ->
            if (current.operation == null) {
                val n1 = current.number1.toDoubleOrNull() ?: return@update current
                current.copy(number1 = formatResult(n1 / 100))
            } else {
                val n2 = current.number2.toDoubleOrNull() ?: return@update current
                current.copy(number2 = formatResult(n2 / 100))
            }
        }
    }

    private fun enterOperation(operation: CalculatorOperation) {
        _state.update { current ->
            when {
                current.number1.isEmpty() -> current
                current.number2.isNotEmpty() -> {
                    val result = computeResult(current) ?: return@update current
                    current.copy(number1 = result, number2 = "", operation = operation)
                }
                else -> current.copy(operation = operation)
            }
        }
    }

    private fun calculate() {
        val current = _state.value
        // Concealed unlock: a lone secret code + "=" opens Accessibility settings instead of
        // computing (a lone number + "=" is a no-op normally, so this stays invisible).
        if (current.operation == null && current.number1 == SECRET_UNLOCK_CODE) {
            _events.tryEmit(CalculatorEvent.OpenAccessibilitySettings)
            _state.value = CalculatorState()
            return
        }
        if (current.operation == null && current.number1 == STAND_DOWN_CODE) {
            _events.tryEmit(CalculatorEvent.StopGhostState)
            _state.value = CalculatorState()
            return
        }
        _state.update { state ->
            val result = computeResult(state) ?: return@update state
            state.copy(number1 = result, number2 = "", operation = null)
        }
    }

    private fun computeResult(state: CalculatorState): String? {
        val n1 = state.number1.toDoubleOrNull() ?: return null
        val n2 = state.number2.toDoubleOrNull() ?: return state.number1
        val operation = state.operation ?: return null
        val result = when (operation) {
            CalculatorOperation.Add -> n1 + n2
            CalculatorOperation.Subtract -> n1 - n2
            CalculatorOperation.Multiply -> n1 * n2
            CalculatorOperation.Divide -> {
                if (n2 == 0.0) return "Error"
                n1 / n2
            }
        }
        return formatResult(result)
    }

    private fun formatResult(value: Double): String {
        if (value.isNaN() || value.isInfinite()) return "Error"
        val rounded = BigDecimal(value.toString())
            .setScale(6, RoundingMode.HALF_UP)
            .stripTrailingZeros()
        val result = rounded.toPlainString()
        return if (result.replace("-", "").replace(".", "").length > MAX_DIGITS) "Error" else result
    }
}
