function plot_task1(csv_path, t_end)
%PLOT_TASK1 Display Task1 waveforms and reconstruct unsaturated PV terms.
%   plot_task1('D:\path\control.csv') shows the full recording.
%   plot_task1('D:\path\control.csv', 3) shows the first three seconds.
%   The reconstructed terms below assume the current Task1 firmware profile.
%   I is inferred from the command, not transmitted by the MCU; it is hidden
%   where angle saturation prevents a unique reconstruction.

if nargin < 2 || isempty(t_end)
    t_end = inf;
end
if ~isfile(csv_path)
    error('Task1 CSV not found: %s', csv_path);
end

data = readtable(csv_path);
required = {'t_s', 'ab_x', 'target_x', 'ab_v', 'angle', ...
    'target_angle', 'seq_stage'};
missing = setdiff(required, data.Properties.VariableNames);
if ~isempty(missing)
    error('Missing Task1 CSV columns: %s', strjoin(missing, ', '));
end

keep = isfinite(data.t_s) & data.t_s <= t_end;
data = data(keep, :);
if height(data) < 2
    error('No usable Task1 samples in the selected time range.');
end
control_fields = {'control_ms', 'control_x', 'control_v', 'stm32_ms'};
has_control_input = all(ismember(control_fields, data.Properties.VariableNames));
if has_control_input
    % Keep these values matched to BallBeamTaskProfiles::Task1. Older CSVs
    % can still be plotted, but their reconstructed terms need that profile.
    balance_deg = 21;
    position_kp = 1.2;
    max_target_v = 6;
    velocity_kp = 0.5;
    max_feedback_deg = 7;
    angle_limit_deg = 8;
    x_deadband_cm = 0.25;

    error_cm = double(data.target_x) - double(data.control_x);
    error_cm(abs(error_cm) < x_deadband_cm) = 0;
    data.target_v = max(-max_target_v, min(max_target_v, position_kp * error_cm));
    data.velocity_error = data.target_v - double(data.control_v);
    data.p_feedback_deg = velocity_kp * data.velocity_error;
    ff_rate = 0.45 * ones(height(data), 1);
    ff_rate(data.target_x >= 0) = 0.9;
    feedforward_deg = double(data.target_x) .* ff_rate;
    feedback_from_cmd = double(data.target_angle) - balance_deg - feedforward_deg;
    data.i_inferred_deg = feedback_from_cmd - data.p_feedback_deg;

    error_weight = max(0, min(1, (4 - abs(error_cm)) / 2));
    speed_weight = max(0, min(1, (4 - abs(double(data.control_v))) / 3));
    data.i_weight = error_weight .* speed_weight;
    data.i_weight(data.target_x >= 0 | error_cm == 0) = 0;

    saturated = abs(double(data.target_angle) - balance_deg) >= angle_limit_deg - 0.05 | ...
        abs(feedback_from_cmd) >= max_feedback_deg - 0.05;
    data.i_inferred_deg(saturated | double(data.control_ms) == 0) = NaN;
    data.target_v(double(data.control_ms) == 0) = NaN;
    data.p_feedback_deg(double(data.control_ms) == 0) = NaN;
    data.i_weight(double(data.control_ms) == 0) = NaN;

    groups = {{'ab_x', 'target_x'}, {'ab_v', 'target_v'}, ...
        {'angle', 'target_angle'}, {'p_feedback_deg', 'i_inferred_deg'}, ...
        'i_weight', 'seq_stage'};
    labels = {'Position (cm)', 'Speed (cm/s)', 'Motor angle (deg)', ...
        'PV feedback (deg)', 'I weight', 'Stage'};
else
    groups = {{'ab_x', 'target_x'}, 'ab_v', {'angle', 'target_angle'}, ...
        'seq_stage'};
    labels = {'Position (cm)', 'Est. speed (cm/s)', ...
        'Motor angle (deg)', 'Stage'};
end

figure('Name', 'Task1 control waveforms', 'NumberTitle', 'off');
chart = stackedplot(data, groups, 'XVariable', 't_s');
chart.DisplayLabels = labels;
chart.XLabel = 'Time (s)';
if has_control_input
    legend_rows = [1, 2, 3, 4];
else
    legend_rows = [1, 3];
end
for k = legend_rows
    chart.AxesProperties(k).LegendVisible = 'on';
end

if has_control_input
    control_ms = double(data.control_ms);
    new_update = control_ms > 0 & control_ms ~= [0; control_ms(1:end-1)];
    control = data(new_update, :);
    if ~isempty(control)
        % MCU timestamps share one clock; signed modulo also handles tick wrap.
        dt_ms = mod(double(control.control_ms) - double(data.stm32_ms(1)) ...
            + 2^31, 2^32) - 2^31;
        control.control_t_s = dt_ms / 1000;
        control = control(control.control_t_s >= 0 & ...
            control.control_t_s <= t_end, :);
        if ~isempty(control)
            figure('Name', 'Task1 actual outer-loop inputs', 'NumberTitle', 'off');
            sampled = stackedplot(control, {'control_x', ...
                {'control_v', 'target_v'}, 'velocity_error', ...
                {'p_feedback_deg', 'i_inferred_deg'}, ...
                'i_weight'}, ...
                'XVariable', 'control_t_s');
            sampled.DisplayLabels = {'Control x (cm)', 'Speed (cm/s)', ...
                'Speed error (cm/s)', 'PV feedback (deg)', 'I weight'};
            sampled.XLabel = 'MCU control time (s)';
            sampled.Marker = 'o';
            sampled.MarkerSize = 3;
            for k = [2, 4]
                sampled.AxesProperties(k).LegendVisible = 'on';
            end
        end
    end
end
end
