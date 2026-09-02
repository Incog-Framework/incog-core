package com.incog.mobileclient.calculator

sealed class CalculatorAction {
    data class Number(val digit: Int) : CalculatorAction()
    data object Decimal : CalculatorAction()
    data object Clear : CalculatorAction()
    data object Delete : CalculatorAction()
    data object ToggleSign : CalculatorAction()
    data object Percent : CalculatorAction()
    data class Operation(val operation: CalculatorOperation) : CalculatorAction()
    data object Calculate : CalculatorAction()
}

enum class CalculatorOperation(val symbol: String) {
    Add("+"),
    Subtract("−"),
    Multiply("×"),
    Divide("÷")
}
