using System;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;

namespace Mixers.Controls;

/// <summary>
/// Slider nativo GPU-acelerado (DirectX) com Brushes congelados (zero alocações por frame):
/// trilha fina de 2px, barra branca de pico ao vivo sobreposta na trilha,
/// pílula vertical slim e scroll do mouse.
/// </summary>
public sealed class VolumeSliderControl : FrameworkElement
{
    private int _value = 100;
    private bool _muted;
    private float _peak;
    private bool _hovered;
    private bool _dragging;

    private SolidColorBrush _accentBrush = CreateFrozen(Color.FromRgb(139, 92, 246));
    private SolidColorBrush _accentHoverBrush = CreateFrozen(Color.FromRgb(167, 139, 250));
    private SolidColorBrush _trackUnfilledBrush = CreateFrozen(Color.FromArgb(135, 165, 160, 190));
    private SolidColorBrush _trackMutedBrush = CreateFrozen(Color.FromArgb(90, 130, 126, 150));
    private SolidColorBrush _thumbMutedBrush = CreateFrozen(Color.FromRgb(115, 110, 138));
    private SolidColorBrush _peakBrush = Brushes.White;
    private Color _peakColor = Colors.White;

    public event Action<int>? ValueChanged;

    public VolumeSliderControl()
    {
        Height = 28;
        Cursor = Cursors.Hand;
        SnapsToDevicePixels = false;
    }

    private static SolidColorBrush CreateFrozen(Color c)
    {
        var b = new SolidColorBrush(c);
        b.Freeze();
        return b;
    }

    public int Value
    {
        get => _value;
        set
        {
            int clamped = Math.Clamp(value, 0, 100);
            if (clamped != _value)
            {
                _value = clamped;
                InvalidateVisual();
            }
        }
    }

    public bool IsMuted
    {
        get => _muted;
        set
        {
            if (value != _muted)
            {
                _muted = value;
                InvalidateVisual();
            }
        }
    }

    public void ApplyColors(Color accent, Color accentHover, Color trackUnfilled, Color trackMuted, Color thumbMuted)
    {
        _accentBrush = CreateFrozen(accent);
        _accentHoverBrush = CreateFrozen(accentHover);
        _trackUnfilledBrush = CreateFrozen(trackUnfilled);
        _trackMutedBrush = CreateFrozen(trackMuted);
        _thumbMutedBrush = CreateFrozen(thumbMuted);
        InvalidateVisual();
    }

    public void SetPeak(float peak, Color? color = null)
    {
        float clamped = Math.Clamp(peak, 0f, 1f);
        bool colorChanged = color.HasValue && color.Value != _peakColor;
        if (Math.Abs(clamped - _peak) < 0.014f && !colorChanged) return;

        _peak = clamped;
        if (colorChanged && color.HasValue)
        {
            _peakColor = color.Value;
            _peakBrush = CreateFrozen(color.Value);
        }
        InvalidateVisual();
    }

    protected override void OnRender(DrawingContext dc)
    {
        double w = ActualWidth;
        double h = ActualHeight;
        if (w < 16 || h < 8) return;

        dc.DrawRectangle(Brushes.Transparent, null, new Rect(0, 0, w, h));

        const double pad = 5.0;
        double x0 = pad;
        double x1 = w - pad;
        double usable = Math.Max(1.0, x1 - x0);
        double cy = h / 2.0;
        double ratio = _value / 100.0;
        double kx = x0 + usable * ratio;

        // 1. Trilha base fina (2px)
        dc.DrawRoundedRectangle(
            _muted ? _trackMutedBrush : _trackUnfilledBrush,
            null,
            new Rect(x0, cy - 1.0, usable, 2.0),
            1.0,
            1.0);

        // 2. Trilha preenchida (volume)
        if (ratio > 0)
        {
            dc.DrawRoundedRectangle(
                _muted ? _thumbMutedBrush : _accentBrush,
                null,
                new Rect(x0, cy - 1.0, Math.Max(2.0, kx - x0), 2.0),
                1.0,
                1.0);
        }

        // 3. Medidor de áudio ao vivo sobreposto na própria trilha
        if (!_muted && _peak > 0.01f && ratio > 0)
        {
            double peakWidth = usable * Math.Min(ratio, _peak * ratio);
            if (peakWidth > 2.0)
            {
                dc.DrawRoundedRectangle(
                    _peakBrush,
                    null,
                    new Rect(x0, cy - 1.2, peakWidth, 2.4),
                    1.2,
                    1.2);
            }
        }

        // 4. Pílula vertical slim (4x15px, expande suavemente no hover)
        double pillW = (_hovered || _dragging) ? 5.0 : 4.0;
        double pillH = (_hovered || _dragging) ? 18.0 : 15.0;
        var thumbBrush = _muted
            ? _thumbMutedBrush
            : ((_hovered || _dragging) ? _accentHoverBrush : _accentBrush);

        dc.DrawRoundedRectangle(
            thumbBrush,
            null,
            new Rect(kx - pillW / 2.0, cy - pillH / 2.0, pillW, pillH),
            pillW / 2.0,
            pillW / 2.0);
    }

    private void UpdateFromPoint(Point pt)
    {
        const double pad = 5.0;
        double usable = Math.Max(1.0, ActualWidth - 2.0 * pad);
        double ratio = Math.Clamp((pt.X - pad) / usable, 0.0, 1.0);
        int newVal = (int)Math.Round(ratio * 100.0);
        if (newVal != _value)
        {
            _value = newVal;
            InvalidateVisual();
            ValueChanged?.Invoke(newVal);
        }
    }

    protected override void OnMouseLeftButtonDown(MouseButtonEventArgs e)
    {
        base.OnMouseLeftButtonDown(e);
        _dragging = true;
        CaptureMouse();
        UpdateFromPoint(e.GetPosition(this));
        e.Handled = true;
    }

    protected override void OnMouseMove(MouseEventArgs e)
    {
        base.OnMouseMove(e);
        if (_dragging) UpdateFromPoint(e.GetPosition(this));
    }

    protected override void OnMouseLeftButtonUp(MouseButtonEventArgs e)
    {
        base.OnMouseLeftButtonUp(e);
        if (_dragging)
        {
            _dragging = false;
            ReleaseMouseCapture();
            InvalidateVisual();
        }
    }

    protected override void OnMouseEnter(MouseEventArgs e)
    {
        base.OnMouseEnter(e);
        _hovered = true;
        InvalidateVisual();
    }

    protected override void OnMouseLeave(MouseEventArgs e)
    {
        base.OnMouseLeave(e);
        _hovered = false;
        InvalidateVisual();
    }

    protected override void OnMouseWheel(MouseWheelEventArgs e)
    {
        base.OnMouseWheel(e);
        int delta = e.Delta > 0 ? 4 : -4;
        int newVal = Math.Clamp(_value + delta, 0, 100);
        if (newVal != _value)
        {
            _value = newVal;
            InvalidateVisual();
            ValueChanged?.Invoke(newVal);
        }
        e.Handled = true;
    }
}
