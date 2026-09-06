package com.incog.mobileclient.calculator

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.CircleShape
import android.content.Intent
import android.provider.Settings
import com.incog.mobileclient.ghost.GhostStateService
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.incog.mobileclient.config.SecretCodes

// Fixed calculator palette (kept theme-independent so the decoy always looks like a normal,
// intentional calculator regardless of the device's light/dark setting).
private val ScreenBg = Color(0xFF17171C)
private val NumberBg = Color(0xFF303036)
private val NumberFg = Color.White
private val FunctionBg = Color(0xFFA5A5AE)
private val FunctionFg = Color(0xFF17171C)
private val OperatorBg = Color(0xFFFF9F0A)
private val OperatorFg = Color.White

private enum class ButtonStyle(val bg: Color, val fg: Color) {
    Number(NumberBg, NumberFg),
    Function(FunctionBg, FunctionFg),
    Operator(OperatorBg, OperatorFg)
}

private data class CalcButton(
    val label: String,
    val action: CalculatorAction,
    val style: ButtonStyle,
    val widthWeight: Float = 1f
)

private val buttonRows: List<List<CalcButton>> = listOf(
    listOf(
        CalcButton("AC", CalculatorAction.Clear, ButtonStyle.Function),
        CalcButton("+/−", CalculatorAction.ToggleSign, ButtonStyle.Function),
        CalcButton("%", CalculatorAction.Percent, ButtonStyle.Function),
        CalcButton("÷", CalculatorAction.Operation(CalculatorOperation.Divide), ButtonStyle.Operator)
    ),
    listOf(
        CalcButton("7", CalculatorAction.Number(7), ButtonStyle.Number),
        CalcButton("8", CalculatorAction.Number(8), ButtonStyle.Number),
        CalcButton("9", CalculatorAction.Number(9), ButtonStyle.Number),
        CalcButton("×", CalculatorAction.Operation(CalculatorOperation.Multiply), ButtonStyle.Operator)
    ),
    listOf(
        CalcButton("4", CalculatorAction.Number(4), ButtonStyle.Number),
        CalcButton("5", CalculatorAction.Number(5), ButtonStyle.Number),
        CalcButton("6", CalculatorAction.Number(6), ButtonStyle.Number),
        CalcButton("−", CalculatorAction.Operation(CalculatorOperation.Subtract), ButtonStyle.Operator)
    ),
    listOf(
        CalcButton("1", CalculatorAction.Number(1), ButtonStyle.Number),
        CalcButton("2", CalculatorAction.Number(2), ButtonStyle.Number),
        CalcButton("3", CalculatorAction.Number(3), ButtonStyle.Number),
        CalcButton("+", CalculatorAction.Operation(CalculatorOperation.Add), ButtonStyle.Operator)
    ),
    listOf(
        CalcButton("⌫", CalculatorAction.Delete, ButtonStyle.Function),
        CalcButton("0", CalculatorAction.Number(0), ButtonStyle.Number),
        CalcButton(".", CalculatorAction.Decimal, ButtonStyle.Number),
        CalcButton("=", CalculatorAction.Calculate, ButtonStyle.Operator)
    )
)

@Composable
fun CalculatorScreen(
    modifier: Modifier = Modifier,
    codes: SecretCodes = SecretCodes(),
    onOpenSettings: () -> Unit = {},
    // Keyed by the codes so reconfiguring them in setup yields a ViewModel that checks the new ones.
    viewModel: CalculatorViewModel = viewModel(
        key = "calculator-${codes.hashCode()}",
        factory = viewModelFactory { initializer { CalculatorViewModel(codes) } }
    )
) {
    val state by viewModel.state.collectAsState()
    val context = LocalContext.current

    LaunchedEffect(viewModel) {
        viewModel.events.collect { event ->
            when (event) {
                CalculatorEvent.OpenAccessibilitySettings -> {
                    context.startActivity(
                        Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    )
                }
                CalculatorEvent.StopGhostState -> {
                    GhostStateService.stop(context)
                }
                CalculatorEvent.OpenSettings -> {
                    onOpenSettings()
                }
            }
        }
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .background(ScreenBg)
            .padding(16.dp),
        verticalArrangement = Arrangement.Bottom
    ) {
        CalculatorDisplay(
            state = state,
            modifier = Modifier.fillMaxWidth().padding(bottom = 16.dp)
        )
        buttonRows.forEach { row ->
            Row(
                modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                row.forEach { button ->
                    CalculatorKey(button = button, onAction = viewModel::onAction)
                }
            }
        }
    }
}

@Composable
private fun CalculatorDisplay(state: CalculatorState, modifier: Modifier = Modifier) {
    val expression = state.operation?.let { "${state.number1} ${it.symbol}" } ?: ""
    val display = when {
        state.operation != null && state.number2.isNotEmpty() -> state.number2
        state.number1.isNotEmpty() -> state.number1
        else -> "0"
    }
    // Shrink the main number as it gets longer so it never wraps or clips off-screen.
    val displayFontSize = when {
        display.length <= 6 -> 80.sp
        display.length <= 9 -> 60.sp
        else -> 44.sp
    }
    Column(
        horizontalAlignment = Alignment.End,
        modifier = modifier
    ) {
        Text(
            text = expression,
            color = FunctionBg,
            fontSize = 26.sp,
            maxLines = 1,
            softWrap = false
        )
        Text(
            text = display,
            color = NumberFg,
            fontSize = displayFontSize,
            fontWeight = FontWeight.Light,
            textAlign = TextAlign.End,
            maxLines = 1,
            softWrap = false
        )
    }
}

@Composable
private fun RowScope.CalculatorKey(button: CalcButton, onAction: (CalculatorAction) -> Unit) {
    Box(
        modifier = Modifier
            .weight(button.widthWeight)
            .aspectRatio(1f)
            .clip(CircleShape)
            .background(button.style.bg)
            .clickable { onAction(button.action) },
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = button.label,
            color = button.style.fg,
            fontSize = 30.sp,
            fontWeight = FontWeight.Medium,
            maxLines = 1,
            softWrap = false
        )
    }
}
