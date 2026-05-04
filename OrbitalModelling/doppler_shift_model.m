clear all; clc;

% Fundamentals:
% The Doppler shifted frequency at any moment is:
% f_received = f_transmitted × (1 + v_radial / c)
% Where v_radial is the component of the satellite's velocity directed toward or
% away from your ground station — positive when approaching, negative when receding. The shift in Hz is:
% Δf = f_transmitted × v_radial / c




fprintf('=================================================================\n');
fprintf('  Doppler Shift Model — Meteor M2-3/M2-4 → B-Raspi Ground Station\n');
fprintf('=================================================================\n\n');


% -------------------------------------------------------------------------
%  1. Get Parameters
% -------------------------------------------------------------------------

run('groundstation_params.m')

% Orbital parameters
v_sat_kms   = 7.5;        % Meteor orbital velocity (km/s) — circular orbit approx
v_sat_ms    = v_sat_kms * 1e3;

% Observation geometry — define a specific pass to model
% These would come from a real SatNOGS observation for Section 5 overlay
el_max_deg  = 82.0;       % Maximum elevation of the pass (degrees)
az_rise_deg = 14.0;       % Azimuth at rise (degrees from North)
az_set_deg  = 201.0;      % Azimuth at set (degrees from North)

R_km   = R_earth_km; % Earth radius (km)
h_km   = alt_km; % Altitude of satellite above Earth surface (km)

% -------------------------------------------------------------------------
%  2. Pass time geometry
% -------------------------------------------------------------------------

% Time vector centred on time of maximum elevation
pass_duration_s = 600;    % Typical Meteor pass ~10 minutes
t = -pass_duration_s/2 : 1 : pass_duration_s/2;   % 1 second steps

% Elevation angle profile — sinusoidal approximation
% Peak elevation occurs at t=0 (time of closest approach)
el_rad_t = deg2rad(el_max_deg) .* cos(pi .* t / pass_duration_s);
el_deg_t = rad2deg(el_rad_t);


% -------------------------------------------------------------------------
%  3. Slant range and range rate
% -------------------------------------------------------------------------


% Slant range at each time step
d_km_t = -R_km .* sin(el_rad_t) + sqrt((R_km + h_km)^2 - R_km^2 .* cos(el_rad_t).^2);

% Range rate — numerical derivative of slant range (km/s)
% Positive = satellite receding, Negative = satellite approaching
d_dot_kms = diff(d_km_t) ./ diff(t);    % km/s
t_mid = t(1:end-1) + 0.5;               % midpoints for plotting


% -------------------------------------------------------------------------
%  4. Doppler shift calculation
% -------------------------------------------------------------------------

% Doppler shift at each time step
% Δf = -f × d_dot / c  (negative sign: approaching = positive shift)
delta_f_Hz = -f_Hz .* (d_dot_kms * 1e3) / c;
delta_f_kHz = delta_f_Hz / 1e3;

% Received frequency at each time step
f_received_MHz = (f_Hz + delta_f_Hz) / 1e6;

% Verifaction Points
fprintf('Maximum Doppler shift (horizon) = %.2f kHz\n', max(abs(delta_f_kHz)));
fprintf('Doppler shift at max elevation  = %.2f kHz\n', delta_f_kHz(length(t_mid)/2));
fprintf('Total sweep (rise to set)       = %.2f kHz\n', delta_f_kHz(1) - delta_f_kHz(end));


% -------------------------------------------------------------------------
%  5. Plotting
% -------------------------------------------------------------------------


% Plot 1: Elevation angle vs time
figure(1);
plot(t, el_deg_t, 'b-', 'LineWidth', 2);
xlabel('Time from closest approach (seconds)');
ylabel('Elevation Angle (degrees)');
title('Pass Geometry — Elevation vs Time');
grid on;

% Plot 2: Doppler shift vs time
figure(2);
plot(t_mid, delta_f_kHz, 'r-', 'LineWidth', 2);
hold on;
yline(0, 'k--', 'LineWidth', 1, 'Label', 'Zero crossing (max elevation)');
xlabel('Time from closest approach (seconds)');
ylabel('Doppler Shift (kHz)');
title('Doppler Shift vs Time — Meteor M2-3/M2-4 @ 137.1 MHz');
grid on;

% Plot 3: Received frequency vs time
figure(3);
plot(t_mid, f_received_MHz, 'g-', 'LineWidth', 2);
yline(f_Hz/1e6, 'k--', 'Label', 'Nominal frequency');
xlabel('Time from closest approach (seconds)');
ylabel('Received Frequency (MHz)');
title('Received Frequency vs Time — Doppler Effect');
grid on;
