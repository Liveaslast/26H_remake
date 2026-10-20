#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <net.h>

namespace py = pybind11;

namespace {

using Clock = std::chrono::steady_clock;
constexpr double kPi = 3.1415926535897932384626433832795;

double elapsed_ms(Clock::time_point start) {
    return std::chrono::duration<double, std::milli>(Clock::now() - start).count();
}

struct Candidate {
    float x1;
    float y1;
    float x2;
    float y2;
    float confidence;
};

struct Circle {
    double center_x;
    double center_y;
    double radius;
};

bool circle_from_three(double x1, double y1, double x2, double y2, double x3, double y3, Circle& circle) {
    const double denominator = 2.0 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2));
    if (std::abs(denominator) < 1e-8) {
        return false;
    }
    const double norm1 = x1 * x1 + y1 * y1;
    const double norm2 = x2 * x2 + y2 * y2;
    const double norm3 = x3 * x3 + y3 * y3;
    circle.center_x = (norm1 * (y2 - y3) + norm2 * (y3 - y1) + norm3 * (y1 - y2)) / denominator;
    circle.center_y = (norm1 * (x3 - x2) + norm2 * (x1 - x3) + norm3 * (x2 - x1)) / denominator;
    circle.radius = std::hypot(x1 - circle.center_x, y1 - circle.center_y);
    return std::isfinite(circle.center_x) && std::isfinite(circle.center_y) && std::isfinite(circle.radius);
}

bool within_circle_limits(const Circle& circle, double box_center_x, double box_center_y,
                          double expected_radius, double max_box_side, double min_radius_ratio,
                          double max_radius_ratio, double max_center_offset_ratio) {
    if (circle.radius < min_radius_ratio * expected_radius || circle.radius > max_radius_ratio * expected_radius) {
        return false;
    }
    const double center_offset = std::hypot(circle.center_x - box_center_x, circle.center_y - box_center_y);
    return center_offset <= max_center_offset_ratio * max_box_side;
}

bool solve_3x3(double matrix[3][4], double solution[3]) {
    for (int column = 0; column < 3; ++column) {
        int pivot = column;
        for (int row = column + 1; row < 3; ++row) {
            if (std::abs(matrix[row][column]) > std::abs(matrix[pivot][column])) {
                pivot = row;
            }
        }
        if (std::abs(matrix[pivot][column]) < 1e-12) {
            return false;
        }
        if (pivot != column) {
            for (int value = column; value < 4; ++value) {
                std::swap(matrix[column][value], matrix[pivot][value]);
            }
        }
        const double divisor = matrix[column][column];
        for (int value = column; value < 4; ++value) {
            matrix[column][value] /= divisor;
        }
        for (int row = 0; row < 3; ++row) {
            if (row == column) {
                continue;
            }
            const double factor = matrix[row][column];
            for (int value = column; value < 4; ++value) {
                matrix[row][value] -= factor * matrix[column][value];
            }
        }
    }
    solution[0] = matrix[0][3];
    solution[1] = matrix[1][3];
    solution[2] = matrix[2][3];
    return std::isfinite(solution[0]) && std::isfinite(solution[1]) && std::isfinite(solution[2]);
}

bool least_squares_circle(const std::vector<std::array<double, 2>>& points,
                          const std::vector<unsigned char>& inliers, Circle& circle) {
    double matrix[3][4]{};
    int count = 0;
    for (size_t index = 0; index < points.size(); ++index) {
        if (!inliers[index]) {
            continue;
        }
        const double x = points[index][0];
        const double y = points[index][1];
        const double row[3] = {2.0 * x, 2.0 * y, 1.0};
        const double target = x * x + y * y;
        for (int left = 0; left < 3; ++left) {
            for (int right = 0; right < 3; ++right) {
                matrix[left][right] += row[left] * row[right];
            }
            matrix[left][3] += row[left] * target;
        }
        ++count;
    }
    if (count < 3) {
        return false;
    }
    double solution[3]{};
    if (!solve_3x3(matrix, solution)) {
        return false;
    }
    const double radius_squared = solution[2] + solution[0] * solution[0] + solution[1] * solution[1];
    if (radius_squared <= 0.0) {
        return false;
    }
    circle = {solution[0], solution[1], std::sqrt(radius_squared)};
    return std::isfinite(circle.center_x) && std::isfinite(circle.center_y) && std::isfinite(circle.radius);
}

float intersection_over_union(const Candidate& first, const Candidate& second) {
    const float left = std::max(first.x1, second.x1);
    const float top = std::max(first.y1, second.y1);
    const float right = std::min(first.x2, second.x2);
    const float bottom = std::min(first.y2, second.y2);
    const float intersection = std::max(0.0f, right - left) * std::max(0.0f, bottom - top);
    if (intersection <= 0.0f) {
        return 0.0f;
    }
    const float first_area = std::max(0.0f, first.x2 - first.x1) * std::max(0.0f, first.y2 - first.y1);
    const float second_area = std::max(0.0f, second.x2 - second.x1) * std::max(0.0f, second.y2 - second.y1);
    return intersection / std::max(1e-6f, first_area + second_area - intersection);
}

class NcnnBackend {
public:
    NcnnBackend(const std::string& model_path, int threads) {
        if (threads <= 0) {
            throw std::invalid_argument("threads must be positive");
        }
        net_.opt.use_vulkan_compute = false;
        net_.opt.num_threads = threads;
        net_.opt.lightmode = true;

        // An empty model path creates a fit-only instance used by the circle
        // refinement adapter; it avoids loading the detector weights again.
        if (model_path.empty()) {
            return;
        }

        const auto started = Clock::now();
        const std::string param_path = model_path + "/model.ncnn.param";
        const std::string bin_path = model_path + "/model.ncnn.bin";
        if (net_.load_param(param_path.c_str()) != 0) {
            throw std::runtime_error("failed to load NCNN parameter file: " + param_path);
        }
        if (net_.load_model(bin_path.c_str()) != 0) {
            throw std::runtime_error("failed to load NCNN model file: " + bin_path);
        }
        model_load_ms_ = elapsed_ms(started);
        model_loaded_ = true;
    }

    py::dict infer(
        const py::array_t<unsigned char, py::array::c_style | py::array::forcecast>& image,
        float confidence_threshold,
        float iou_threshold,
        int max_detections
    ) const {
        if (!model_loaded_) {
            throw std::runtime_error("this native backend instance has no loaded NCNN model");
        }
        if (confidence_threshold < 0.0f || confidence_threshold > 1.0f) {
            throw std::invalid_argument("confidence_threshold must be within [0, 1]");
        }
        if (iou_threshold < 0.0f || iou_threshold > 1.0f) {
            throw std::invalid_argument("iou_threshold must be within [0, 1]");
        }
        if (max_detections <= 0) {
            throw std::invalid_argument("max_detections must be positive");
        }

        const py::buffer_info info = image.request();
        if (info.ndim != 3 || info.shape[2] != 3) {
            throw std::invalid_argument("image must have shape (height, width, 3)");
        }
        const int width = static_cast<int>(info.shape[1]);
        const int height = static_cast<int>(info.shape[0]);
        if (width <= 0 || height <= 0) {
            throw std::invalid_argument("image dimensions must be positive");
        }

        const auto preprocess_started = Clock::now();
        const auto* pixels = static_cast<const unsigned char*>(info.ptr);
        ncnn::Mat input = ncnn::Mat::from_pixels(pixels, ncnn::Mat::PIXEL_BGR2RGB, width, height);
        const float norm_values[3] = {1.0f / 255.0f, 1.0f / 255.0f, 1.0f / 255.0f};
        input.substract_mean_normalize(nullptr, norm_values);
        const double preprocess_ms = elapsed_ms(preprocess_started);

        ncnn::Extractor extractor = net_.create_extractor();
        const auto inference_started = Clock::now();
        if (extractor.input("in0", input) != 0) {
            throw std::runtime_error("failed to set NCNN input blob 'in0'");
        }
        ncnn::Mat output;
        if (extractor.extract("out0", output) != 0) {
            throw std::runtime_error("failed to extract NCNN output blob 'out0'");
        }
        const double inference_ms = elapsed_ms(inference_started);

        const auto postprocess_started = Clock::now();
        std::vector<Candidate> candidates;
        const int rows = output.h;
        const int columns = output.w;
        auto value = [&output, rows, columns](int row, int column) -> float {
            if (rows == 5) {
                return output.row(row)[column];
            }
            if (columns == 5) {
                return output.row(column)[row];
            }
            throw std::runtime_error("unexpected NCNN output shape; expected one dimension to equal 5");
        };
        const int count = rows == 5 ? columns : (columns == 5 ? rows : 0);
        if (count == 0) {
            throw std::runtime_error("unexpected NCNN output shape");
        }
        candidates.reserve(static_cast<size_t>(count));
        for (int index = 0; index < count; ++index) {
            const float center_x = value(0, index);
            const float center_y = value(1, index);
            const float box_width = value(2, index);
            const float box_height = value(3, index);
            const float score = value(4, index);
            if (!std::isfinite(center_x) || !std::isfinite(center_y) ||
                !std::isfinite(box_width) || !std::isfinite(box_height) ||
                !std::isfinite(score) || score < confidence_threshold ||
                box_width <= 0.0f || box_height <= 0.0f) {
                continue;
            }
            candidates.push_back({
                std::max(0.0f, center_x - box_width * 0.5f),
                std::max(0.0f, center_y - box_height * 0.5f),
                std::min(static_cast<float>(width), center_x + box_width * 0.5f),
                std::min(static_cast<float>(height), center_y + box_height * 0.5f),
                score,
            });
        }
        std::sort(candidates.begin(), candidates.end(), [](const Candidate& first, const Candidate& second) {
            return first.confidence > second.confidence;
        });
        std::vector<Candidate> selected;
        selected.reserve(std::min(static_cast<size_t>(max_detections), candidates.size()));
        for (const Candidate& candidate : candidates) {
            bool suppressed = false;
            for (const Candidate& kept : selected) {
                if (intersection_over_union(candidate, kept) > iou_threshold) {
                    suppressed = true;
                    break;
                }
            }
            if (!suppressed) {
                selected.push_back(candidate);
                if (static_cast<int>(selected.size()) >= max_detections) {
                    break;
                }
            }
        }
        const double postprocess_ms = elapsed_ms(postprocess_started);

        py::array_t<float> boxes({static_cast<py::ssize_t>(selected.size()), static_cast<py::ssize_t>(6)});
        auto result = boxes.mutable_unchecked<2>();
        for (py::ssize_t index = 0; index < static_cast<py::ssize_t>(selected.size()); ++index) {
            const Candidate& candidate = selected[static_cast<size_t>(index)];
            result(index, 0) = candidate.x1;
            result(index, 1) = candidate.y1;
            result(index, 2) = candidate.x2;
            result(index, 3) = candidate.y2;
            result(index, 4) = candidate.confidence;
            result(index, 5) = 0.0f;
        }

        py::dict output_dict;
        output_dict["boxes"] = boxes;
        output_dict["model_load_ms"] = model_load_ms_;
        output_dict["preprocess_ms"] = preprocess_ms;
        output_dict["inference_ms"] = inference_ms;
        output_dict["postprocess_ms"] = postprocess_ms;
        output_dict["raw_candidate_count"] = static_cast<int>(candidates.size());
        return output_dict;
    }

    py::dict refine_ransac(
        const py::array_t<double, py::array::c_style | py::array::forcecast>& points_array,
        const py::array_t<long long, py::array::c_style | py::array::forcecast>& samples_array,
        double box_center_x,
        double box_center_y,
        double expected_radius,
        double max_box_side,
        double min_radius_ratio,
        double max_radius_ratio,
        double max_center_offset_ratio,
        double inlier_threshold_px,
        int min_inliers,
        int angle_bins,
        double min_arc_coverage,
        double max_mean_residual_px
    ) const {
        const auto started = Clock::now();
        const py::buffer_info points_info = points_array.request();
        const py::buffer_info samples_info = samples_array.request();
        if (points_info.ndim != 2 || points_info.shape[1] != 2) {
            throw std::invalid_argument("points must have shape (N, 2)");
        }
        if (samples_info.ndim != 2 || samples_info.shape[1] != 3) {
            throw std::invalid_argument("sample_indices must have shape (I, 3)");
        }
        if (expected_radius <= 0.0 || max_box_side <= 0.0 || inlier_threshold_px <= 0.0 ||
            min_inliers < 3 || angle_bins < 4 || min_arc_coverage < 0.0 || min_arc_coverage > 1.0 ||
            max_mean_residual_px <= 0.0) {
            throw std::invalid_argument("invalid circle refinement parameters");
        }

        const auto* point_values = static_cast<const double*>(points_info.ptr);
        const auto* sample_values = static_cast<const long long*>(samples_info.ptr);
        const size_t point_count = static_cast<size_t>(points_info.shape[0]);
        const size_t sample_count = static_cast<size_t>(samples_info.shape[0]);
        std::vector<std::array<double, 2>> points;
        points.reserve(point_count);
        for (size_t index = 0; index < point_count; ++index) {
            points.push_back({point_values[index * 2], point_values[index * 2 + 1]});
        }

        py::dict result;
        result["success"] = false;
        result["center_x"] = box_center_x;
        result["center_y"] = box_center_y;
        result["radius"] = expected_radius;
        result["arc_coverage"] = 0.0;
        result["mean_residual_px"] = py::none();
        result["inlier_count"] = 0;
        result["candidate_count"] = static_cast<int>(point_count);
        result["reason"] = "RANSAC did not find a geometrically valid circle";

        std::vector<unsigned char> best_inliers(point_count, 0);
        int best_inlier_count = -1;
        double best_mean_residual = std::numeric_limits<double>::infinity();
        for (size_t sample_index = 0; sample_index < sample_count; ++sample_index) {
            const long long first_index = sample_values[sample_index * 3];
            const long long second_index = sample_values[sample_index * 3 + 1];
            const long long third_index = sample_values[sample_index * 3 + 2];
            if (first_index < 0 || second_index < 0 || third_index < 0 ||
                first_index >= static_cast<long long>(point_count) ||
                second_index >= static_cast<long long>(point_count) ||
                third_index >= static_cast<long long>(point_count)) {
                continue;
            }
            Circle candidate{};
            const auto& first = points[static_cast<size_t>(first_index)];
            const auto& second = points[static_cast<size_t>(second_index)];
            const auto& third = points[static_cast<size_t>(third_index)];
            if (!circle_from_three(first[0], first[1], second[0], second[1], third[0], third[1], candidate) ||
                !within_circle_limits(candidate, box_center_x, box_center_y, expected_radius, max_box_side,
                                      min_radius_ratio, max_radius_ratio, max_center_offset_ratio)) {
                continue;
            }

            std::vector<unsigned char> inliers(point_count, 0);
            int inlier_count = 0;
            double residual_sum = 0.0;
            for (size_t point_index = 0; point_index < point_count; ++point_index) {
                const double residual = std::abs(std::hypot(points[point_index][0] - candidate.center_x,
                                                             points[point_index][1] - candidate.center_y) - candidate.radius);
                if (residual <= inlier_threshold_px) {
                    inliers[point_index] = 1;
                    ++inlier_count;
                    residual_sum += residual;
                }
            }
            if (inlier_count < min_inliers) {
                continue;
            }
            const double mean_residual = residual_sum / static_cast<double>(inlier_count);
            if (inlier_count > best_inlier_count ||
                (inlier_count == best_inlier_count && mean_residual < best_mean_residual)) {
                best_inliers = std::move(inliers);
                best_inlier_count = inlier_count;
                best_mean_residual = mean_residual;
            }
        }

        if (best_inlier_count < min_inliers) {
            result["ransac_ms"] = elapsed_ms(started);
            return result;
        }
        Circle refined{};
        if (!least_squares_circle(points, best_inliers, refined)) {
            result["reason"] = "least-squares circle refinement failed";
            result["inlier_count"] = best_inlier_count;
            result["ransac_ms"] = elapsed_ms(started);
            return result;
        }
        if (!within_circle_limits(refined, box_center_x, box_center_y, expected_radius, max_box_side,
                                  min_radius_ratio, max_radius_ratio, max_center_offset_ratio)) {
            result["reason"] = "refined circle failed geometry limits";
            result["inlier_count"] = best_inlier_count;
            result["ransac_ms"] = elapsed_ms(started);
            return result;
        }

        std::vector<size_t> final_indices;
        final_indices.reserve(point_count);
        double final_residual_sum = 0.0;
        for (size_t point_index = 0; point_index < point_count; ++point_index) {
            const double residual = std::abs(std::hypot(points[point_index][0] - refined.center_x,
                                                         points[point_index][1] - refined.center_y) - refined.radius);
            if (residual <= inlier_threshold_px) {
                final_indices.push_back(point_index);
                final_residual_sum += residual;
            }
        }
        const int final_inlier_count = static_cast<int>(final_indices.size());
        const double final_mean_residual = final_inlier_count > 0
            ? final_residual_sum / static_cast<double>(final_inlier_count)
            : 0.0;
        result["center_x"] = refined.center_x;
        result["center_y"] = refined.center_y;
        result["radius"] = refined.radius;
        result["inlier_count"] = final_inlier_count;
        result["mean_residual_px"] = final_mean_residual;
        if (final_inlier_count < min_inliers) {
            result["reason"] = "too few inliers after least-squares refinement";
            result["ransac_ms"] = elapsed_ms(started);
            return result;
        }

        std::vector<unsigned char> occupied(static_cast<size_t>(angle_bins), 0);
        int occupied_count = 0;
        for (const size_t point_index : final_indices) {
            double angle = std::atan2(points[point_index][1] - refined.center_y,
                                      points[point_index][0] - refined.center_x);
            if (angle < 0.0) {
                angle += 2.0 * kPi;
            }
            int bin = static_cast<int>(std::floor(angle / (2.0 * kPi) * angle_bins));
            bin = std::max(0, std::min(angle_bins - 1, bin));
            if (!occupied[static_cast<size_t>(bin)]) {
                occupied[static_cast<size_t>(bin)] = 1;
                ++occupied_count;
            }
        }
        const double arc_coverage = static_cast<double>(occupied_count) / static_cast<double>(angle_bins);
        result["arc_coverage"] = arc_coverage;
        result["ransac_ms"] = elapsed_ms(started);
        if (arc_coverage < min_arc_coverage) {
            result["reason"] = "arc coverage below threshold";
            return result;
        }
        if (final_mean_residual > max_mean_residual_px) {
            result["reason"] = "mean circle residual above threshold";
            return result;
        }
        result["success"] = true;
        result["reason"] = "circle fit quality checks passed";
        return result;
    }

private:
    mutable ncnn::Net net_;
    double model_load_ms_ = 0.0;
    bool model_loaded_ = false;
};

}  // namespace

PYBIND11_MODULE(_ncnn_cpp, module) {
    module.doc() = "Native NCNN inference backend for ball_detect_yolo_combind";
    py::class_<NcnnBackend>(module, "NcnnBackend")
        .def(py::init<const std::string&, int>(), py::arg("model_path"), py::arg("threads") = 2)
        .def("infer", &NcnnBackend::infer,
             py::arg("image"), py::arg("confidence_threshold") = 0.35f,
             py::arg("iou_threshold") = 0.70f, py::arg("max_detections") = 300)
        .def("refine_ransac", &NcnnBackend::refine_ransac,
             py::arg("points"), py::arg("sample_indices"),
             py::arg("box_center_x"), py::arg("box_center_y"),
             py::arg("expected_radius"), py::arg("max_box_side"),
             py::arg("min_radius_ratio"), py::arg("max_radius_ratio"),
             py::arg("max_center_offset_ratio"), py::arg("inlier_threshold_px"),
             py::arg("min_inliers"), py::arg("angle_bins"),
             py::arg("min_arc_coverage"), py::arg("max_mean_residual_px"));
}
