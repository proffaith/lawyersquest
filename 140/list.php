<?php

echo "<div class='container'>";

if(isset($_GET["nav"])) { $theway=$_GET["nav"]; } else { $theway=0; }

//echo "the way set to: ".$theway;

$cases_by_subject = [];

// Build the HTML table
if (mysqli_num_rows($result) > 0) {
  while($row = mysqli_fetch_assoc($result)) {
      $subject = $row['subject_matter_keywords'];
      if (!isset($cases_by_subject[$subject])) {
          $cases_by_subject[$subject] = [];
      }
      $cases_by_subject[$subject][] = $row;
  }

  // Generate the HTML
      foreach ($cases_by_subject as $subject => $casesList) {
          echo "<div class='subject'>";
          echo "<button class='collapsible'>$subject</button>";
          echo "<div class='content'>";
          foreach ($casesList as $case) {



              echo "<p>";
              echo "<strong>Parties:</strong> " . $case['parties'] . "<br>";
              echo "<strong>Citation:</strong> " . $case['citation'] . "<br>";
              echo "<strong>URL:</strong> <a href='" . $case['URL'] . "' target='_blank'>" . $case['URL'] . "</a><br>";
              echo "<strong>Snippet:</strong> " . $case['snippet'] . "<br>";
              echo "<form method='POST' action='index.php'>";
              echo "<input type='hidden' name='record_id' value='" . $case["id"] . "'>";
              echo "<input type='hidden' name='return_to' value='" . $theway  . "'>";
              echo "<input type='hidden' name='nav' value='10'>";
              echo "<select name='reviewstatus'>";
              echo "<option value=1 " . ($case["reviewed"] == '1' ? "selected" : "") . ">Reviewed</option>";
              echo "<option value=0 " . ($case["reviewed"] == '0' ? "selected" : "") . ">Unreviewed</option>";
              echo "</select>";
              echo "<input type='submit' value='Update'>";
              echo "</form>";
              echo "</p>";
          }
          echo "</div>";
          echo "</div>";
      }

/*
    echo "<table><thead>";
    echo "<tr align='center'>";
    echo "<th valign='center'>Case</th>";
    echo "<th valign='center'>Snippet</th>";
    echo "<th valign='center'>Citation</th>";
    echo "<th valign='center'>General Subject Area</th>";
    echo "<th valign='center'>Action</th>";
    echo "</tr></thead>";

    while ($row = mysqli_fetch_assoc($result)) {
        $wherefrom=$row['cites_to'];
        if(isset($_GET["nav"])) { $theway=$_GET["nav"]; } else { $theway=0; }

        echo "<tr>";
        echo "<td valign='center'><a href='" . $row["URL"] ."' target='_blank'>" . $row["parties"] . "</a></td>";
        echo "<td>" . $row["snippet"] . "</td>";
        echo "<td valign='center'>" . $row["citation"] . "</td>";
        echo "<td valign='center'>" . $row["subject_matter_keywords"] . "</td>";
        echo "<td>";
        echo "<form method='POST' action='index.php'>";
        echo "<input type='hidden' name='record_id' value='" . $row["id"] . "'>";
        echo "<input type='hidden' name='return_to' value='" . $theway  . "'>";
        echo "<input type='hidden' name='nav' value='10'>";
        echo "<select name='reviewstatus'>";
        echo "<option value=1 " . ($row["reviewed"] == '1' ? "selected" : "") . ">Reviewed</option>";
        echo "<option value=0 " . ($row["reviewed"] == '0' ? "selected" : "") . ">Unreviewed</option>";
        echo "</select>";
        echo "<input type='submit' value='Update'>";
        echo "</form>";
        echo "</td>";
        echo "</tr>";

        if($wherefrom) {
          $sql="select parties, citation, URL from mngt140cases where id=$wherefrom;";
          //print($sql);
          $priorcites = $conn->query( $sql );
          $priorcite=mysqli_fetch_assoc($priorcites);

          $row_cnt = $priorcites -> num_rows;
          if ($row_cnt>0) {
            $pc=$priorcite['parties'];
            $thecite=$priorcite['citation'];
            $thisURL=$priorcite['URL'];

            echo "<tr>";
            echo "<td></td>";
            echo "<td align='right'><b>citing to:</b></td>";
            echo "<td><i>$pc</i></td>";
            echo "<td><p>$thecite <a href='$thisURL' target='_blank'>link to cited case</a></td>";
            echo "<td></td>";
            echo "<td></td>";
            echo "<td></td>";
            echo "</tr>";
          }
        }

        }
*/

    echo "</div></table>";
    echo "<p>A total of ". mysqli_num_rows($result)." records were returned.<br>";
} else {
    echo "<p>No data found.";
}



// Close
?>
