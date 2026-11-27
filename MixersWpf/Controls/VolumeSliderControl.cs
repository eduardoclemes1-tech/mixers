using System;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;

namespace Mixers.Controls;

/// <summary>
/// Slider nativo GPU-acelerado (DirectX) fiel ao EarTrumpet / Windows 11:
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

    private Color _accent = Color.FromRgb(139, 92, 246);
    private Color _accentHover = Color.FromRgb(167, 139, 250);
    private Color _trackUnfilled = Color.FromArgb(135, 165, 160, 190);
    private Color _trackMuted = Color.FromArgb(90, 130, 126, 150);
    private Color _thumbMuted = Color.FromRgb(115, 110, 138);
    private Color _peakColor = Colors.White;

    public event Action<int>? ValueChanged;

    public VolumeSliderControl()
    {
        Height = 28;
        Cursor = Cursors.Hand;
        SnapsToDevicePixels = false;
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
        _accent = accent;
        _accentHover = accentHover;
        _trackUnfilled = trackUnfilled;
        _trackMuted = trackMuted;
        _thumbMuted = thumbMuted;
        InvalidateVisual();
    }

    public void SetPeak(float peak, Color? color = null)
    {
        float clamped = Math.Clamp(peak, 0f, 1f);
        bool colorChanged = color.HasValue && color.Value != _peakColor;
        if (Math.Abs(clamped - _peak) < 0.012f && !colorChanged) return;

        _peak = clamped;
        if (color.HasValue) _peakColor = color.Value;
        InvalidateVisual();
    }

    protected override void OnRender(DrawingContext dc)
    {
        double w = ActualWidth;
        double h = ActualHeight;
        if (w < 16 || h < 8) return;

        // Hit-test transparente em toda a área do controle
        dc.DrawRectangle(Brushes.Transparent, null, new Rect(0, 0, w, h));

        const double pad = 5.0;
        double x0 = pad;
        double x1 = w - pad;
        double usable = Math.Max(1.0, x1 - x0);
        double cy = h / 2.0;
        double ratio = _value / 100.0;
        double kx = x0 + usable * ratio;

        // 1. Trilha base fina (2px)
        var trackBrush = new SolidColorBrush(_muted ? _trackMuted : _trackUnfilled);
        dc.DrawRoundedRectangle(trackBrush, null, new Rect(x0, cy - 1.0, usable, 2.0), 1.0, 1.0);

        // 2. Trilha preenchida (volume)
        if (ratio > 0)
        {
            var fillBrush = new SolidColorBrush(_muted ? _thumbMuted : _accent);
            dc.DrawRoundedRectangle(fillBrush, null, new Rect(x0, cy - 1.0, Math.Max(2.0, kx - x0), 2.0), 1.0, 1.0);
        }

        // 3. Medidor de áudio ao vivo sobreposto na própria trilha
        if (!_muted && _peak > 0.01f && ratio > 0)
        {
            double peakWidth = usable * Math.Min(ratio, _peak * ratio);
            if (peakWidth > 2.0)
            {
                var peakBrush = new SolidColorBrush(_peakColor);
                dc.DrawRoundedRectangle(peakBrush, null, new Rect(x0, cy - 1.2, peakWidth, 2.4), 1.2, 1.2);
            }
        }

        // 4. Pílula vertical slim (4x16px, expande suavemente no hover)
        double pillW = (_hovered || _dragging) ? 5.0 : 4.0;
        double pillH = (_hovered || _dragging) ? 18.0 : 15.0;
        Color thumbCol = _muted ? _thumbMuted : ((_hovered || _dragging) ? _accentHover : _accent);
        var thumbBrush = new SolidColorBrush(thumbCol);
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
        if (_dragging)
        {
            UpdateFromPoint(e.GetPosition(this));
        }
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
